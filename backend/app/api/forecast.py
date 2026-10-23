"""Forecasting API endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
import pandas as pd
import json
from datetime import datetime, timedelta

from app.core.database import get_session
from app.models.db_models import Dataset, ForecastRun
from app.models.schemas import ForecastRequest, ForecastResponse, ForecastPoint
from app.ml.forecaster import EnerShareForecaster
from app.services.demo_data import generate_demo_dataset, get_demo_records_as_list

router = APIRouter()


def _load_dataset_df(dataset_id: str, session: Session) -> pd.DataFrame:
    """Load dataset as DataFrame from DB or demo."""
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    if ds.source == "demo":
        return generate_demo_dataset(days=30)

    from app.core.config import settings
    import os
    path = settings.uploads_dir / f"{dataset_id}.csv"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Dataset file not found on disk.")
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@router.post("", response_model=ForecastResponse)
async def generate_forecast(body: ForecastRequest, session: Session = Depends(get_session)):
    """Train model on dataset and generate forecast for the horizon."""
    # Map target
    target_col = "solar_kwh" if body.target == "generation" else "demand_kwh"
    
    df = _load_dataset_df(body.dataset_id, session)

    # Create forecaster
    forecaster = EnerShareForecaster(
        target=target_col,
        model_name=body.model_name,
    )

    # Train
    train_result = forecaster.fit(df)

    # Generate predictions on the last `horizon_hours` rows
    horizon = min(body.horizon_hours, len(df))
    predictions, pred_warnings = forecaster.predict(df, horizon=horizon)

    # Build forecast points
    last_ts = df["timestamp"].iloc[-1]
    points: List[ForecastPoint] = []
    for i, pred in enumerate(predictions):
        ts = last_ts + timedelta(hours=i + 1)
        # Check if actual exists at this position
        row_idx = len(df) - horizon + i
        actual = None
        if 0 <= row_idx < len(df) and target_col in df.columns:
            actual = float(df[target_col].iloc[row_idx])

        points.append(ForecastPoint(
            timestamp=ts,
            actual=actual,
            predicted=round(pred, 4),
            source="demo_forecast",
        ))

    # Save run to DB
    run = ForecastRun(
        dataset_id=body.dataset_id,
        target=body.target,
        model_name=forecaster.effective_model_name,
        horizon_hours=body.horizon_hours,
        mae=train_result.get("val_mae"),
        rmse=train_result.get("val_rmse"),
        mape=train_result.get("val_mape"),
        baseline_mae=train_result.get("baseline_mae"),
        baseline_rmse=train_result.get("baseline_rmse"),
        feature_list=json.dumps(forecaster.feature_names[:20]),
        warnings=json.dumps(forecaster.warnings + pred_warnings),
        results_json=json.dumps([p.model_dump(mode="json") for p in points]),
        status=train_result.get("status", "done"),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    all_warnings = forecaster.warnings + pred_warnings
    if train_result.get("status") != "trained":
        all_warnings.insert(0, f"Training status: {train_result.get('status')}. Using baseline forecast.")

    return ForecastResponse(
        run_id=run.id,
        target=body.target,
        model_name=forecaster.effective_model_name,
        horizon_hours=body.horizon_hours,
        mae=run.mae,
        rmse=run.rmse,
        mape=run.mape,
        baseline_mae=run.baseline_mae,
        baseline_rmse=run.baseline_rmse,
        points=points,
        warnings=all_warnings,
        feature_list=forecaster.feature_names[:20],
        status=train_result.get("status", "done"),
    )


@router.get("/runs")
async def list_forecast_runs(session: Session = Depends(get_session)):
    """List past forecast runs."""
    runs = session.exec(select(ForecastRun)).all()
    return [
        {
            "id": r.id,
            "dataset_id": r.dataset_id,
            "target": r.target,
            "model_name": r.model_name,
            "mae": r.mae,
            "rmse": r.rmse,
            "baseline_mae": r.baseline_mae,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_forecast_run(run_id: str, session: Session = Depends(get_session)):
    """Get details of a specific forecast run."""
    run = session.get(ForecastRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Forecast run not found.")
    return {
        "id": run.id,
        "target": run.target,
        "model_name": run.model_name,
        "mae": run.mae,
        "rmse": run.rmse,
        "mape": run.mape,
        "baseline_mae": run.baseline_mae,
        "baseline_rmse": run.baseline_rmse,
        "warnings": json.loads(run.warnings) if run.warnings else [],
        "feature_list": json.loads(run.feature_list) if run.feature_list else [],
        "results": json.loads(run.results_json) if run.results_json else [],
        "status": run.status,
        "created_at": run.created_at,
    }
