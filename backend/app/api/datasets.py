"""Dataset management API endpoints."""
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from typing import List, Optional
import pandas as pd
import json
import io
from datetime import datetime

from app.core.database import get_session
from app.models.db_models import Dataset
from app.models.schemas import DatasetSummary, DatasetValidationResult
from app.services.demo_data import generate_demo_dataset, get_demo_records_as_list

router = APIRouter()

REQUIRED_COLUMNS = {"timestamp", "solar_kwh", "demand_kwh"}
OPTIONAL_COLUMNS = {
    "wind_kwh", "irradiance_wm2", "temperature_c", "cloud_cover_pct",
    "wind_speed_ms", "import_tariff_inr_kwh", "export_tariff_inr_kwh",
}


@router.get("/demo")
async def get_demo_data(days: int = 7, session: Session = Depends(get_session)):
    """Return demo dataset records (default: 7 days for quick loading)."""
    records = get_demo_records_as_list(days=min(days, 30))

    # Ensure demo dataset is registered in DB
    existing = session.exec(
        select(Dataset).where(Dataset.source == "demo")
    ).first()
    if not existing:
        full_df = generate_demo_dataset(days=30)
        ds = Dataset(
            name="Demo MSME Site — 30 Days",
            source="demo",
            row_count=len(full_df),
            start_timestamp=full_df["timestamp"].iloc[0].to_pydatetime(),
            end_timestamp=full_df["timestamp"].iloc[-1].to_pydatetime(),
            interval_hours=1.0,
            has_solar=True,
            has_wind=False,
            has_weather=True,
        )
        session.add(ds)
        session.commit()
        session.refresh(ds)
        dataset_id = ds.id
    else:
        dataset_id = existing.id

    return {
        "dataset_id": dataset_id,
        "source": "demo",
        "days_returned": days,
        "record_count": len(records),
        "data_quality_note": "All values are SIMULATED demo data, not real measurements.",
        "records": records,
    }


@router.get("", response_model=List[DatasetSummary])
async def list_datasets(session: Session = Depends(get_session)):
    """List all available datasets."""
    datasets = session.exec(select(Dataset)).all()
    result = []
    for ds in datasets:
        warnings = json.loads(ds.quality_warnings) if ds.quality_warnings else []
        result.append(DatasetSummary(
            id=ds.id,
            name=ds.name,
            source=ds.source,
            row_count=ds.row_count,
            start_timestamp=ds.start_timestamp,
            end_timestamp=ds.end_timestamp,
            interval_hours=ds.interval_hours,
            has_solar=ds.has_solar,
            has_wind=ds.has_wind,
            quality_warnings=warnings,
            created_at=ds.created_at,
        ))
    return result


@router.post("/validate", response_model=DatasetValidationResult)
async def validate_csv(file: UploadFile = File(...)):
    """Validate an uploaded CSV file without importing it."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit.")

    errors: List[str] = []
    warnings: List[str] = []

    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {str(e)}")

    cols_found = list(df.columns)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_required:
        errors.append(f"Missing required columns: {missing_required}")

    # Timestamp validation
    dup_count = 0
    if "timestamp" in df.columns:
        try:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            dup_count = int(df["timestamp"].duplicated().sum())
            if dup_count > 0:
                warnings.append(f"{dup_count} duplicate timestamps detected.")
        except Exception:
            errors.append("'timestamp' column cannot be parsed as datetime.")

    # Missing values
    missing_values: dict = {}
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        if n_missing > 0:
            missing_values[col] = n_missing
            if col in REQUIRED_COLUMNS:
                errors.append(f"Required column '{col}' has {n_missing} missing values.")
            else:
                warnings.append(f"Column '{col}' has {n_missing} missing values (will be handled).")

    # Range checks
    if "solar_kwh" in df.columns and (df["solar_kwh"] < 0).any():
        errors.append("'solar_kwh' contains negative values.")
    if "demand_kwh" in df.columns and (df["demand_kwh"] < 0).any():
        errors.append("'demand_kwh' contains negative values.")
    if "battery_soc_pct" in df.columns:
        if (df["battery_soc_pct"] < 0).any() or (df["battery_soc_pct"] > 100).any():
            errors.append("'battery_soc_pct' values must be between 0 and 100.")

    preview = df.head(5).fillna("").to_dict(orient="records")

    return DatasetValidationResult(
        valid=len(errors) == 0,
        row_count=len(df),
        warnings=warnings,
        errors=errors,
        columns_found=cols_found,
        missing_required_columns=missing_required,
        duplicate_timestamps=dup_count,
        missing_values=missing_values,
        preview=preview,
    )


@router.post("/import")
async def import_csv(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """Import a validated CSV file as a new dataset."""
    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").drop_duplicates("timestamp")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")

    missing_req = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_req:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot import: missing required columns {missing_req}"
        )

    warnings = []
    if df["solar_kwh"].isna().any():
        df["solar_kwh"] = df["solar_kwh"].fillna(0)
        warnings.append("Missing solar_kwh filled with 0.")
    if df["demand_kwh"].isna().any():
        df["demand_kwh"] = df["demand_kwh"].fillna(df["demand_kwh"].median())
        warnings.append("Missing demand_kwh filled with median.")

    # Detect interval
    if len(df) > 1:
        diff = (df["timestamp"].iloc[1] - df["timestamp"].iloc[0]).total_seconds() / 3600
        interval_h = round(diff, 2)
    else:
        interval_h = 1.0

    ds = Dataset(
        name=file.filename.replace(".csv", ""),
        source="upload",
        filename=file.filename,
        row_count=len(df),
        start_timestamp=df["timestamp"].iloc[0].to_pydatetime(),
        end_timestamp=df["timestamp"].iloc[-1].to_pydatetime(),
        interval_hours=interval_h,
        has_solar="solar_kwh" in df.columns,
        has_wind="wind_kwh" in df.columns,
        has_weather="irradiance_wm2" in df.columns,
        quality_warnings=json.dumps(warnings),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)

    # Save data file
    import os
    from app.core.config import settings
    os.makedirs(settings.uploads_dir, exist_ok=True)
    save_path = settings.uploads_dir / f"{ds.id}.csv"
    df.to_csv(save_path, index=False)

    return {
        "dataset_id": ds.id,
        "name": ds.name,
        "row_count": len(df),
        "warnings": warnings,
        "message": "Dataset imported successfully.",
    }


@router.get("/template")
async def download_template():
    """Download a sample CSV template."""
    sample_df = generate_demo_dataset(days=2)
    csv_bytes = sample_df.to_csv(index=False).encode()
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=enershare_template.csv"},
    )


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, session: Session = Depends(get_session)):
    """Get a specific dataset's metadata and sample records."""
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    if ds.source == "demo":
        records = get_demo_records_as_list(days=7)
    else:
        import os
        from app.core.config import settings
        save_path = settings.uploads_dir / f"{ds.id}.csv"
        if os.path.exists(save_path):
            df = pd.read_csv(save_path)
            records = df.head(168).fillna("").to_dict(orient="records")  # 1 week
        else:
            records = []

    return {
        "id": ds.id,
        "name": ds.name,
        "source": ds.source,
        "row_count": ds.row_count,
        "interval_hours": ds.interval_hours,
        "records": records,
    }
