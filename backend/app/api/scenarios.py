"""Scenario management API endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
import json
from datetime import datetime

from app.core.database import get_session
from app.models.db_models import Scenario, Dataset
from app.models.schemas import ScenarioCreate, ScenarioResponse

router = APIRouter()

PRESET_DESCRIPTIONS = {
    "solar_surplus": "Solar generation greatly exceeds site demand. Tests storage, export, and curtailment.",
    "deficit": "Renewable generation is insufficient. Tests battery discharge and grid import.",
    "low_battery": "Battery starts near minimum SOC. Tests discharge restriction.",
    "high_tariff": "High import tariff period. Tests value of storage and scheduling.",
    "export_disabled": "Grid export is prohibited. Tests curtailment handling.",
    "ev_demand": "EV charging demand available during evening window.",
    "cloudy": "Low solar due to heavy cloud cover. Tests demand-supply gap management.",
    "battery_full": "Battery starts near full. Tests charge limit handling.",
}


@router.get("/presets")
async def get_presets():
    """List available preset scenarios."""
    return [
        {"preset": k, "description": v}
        for k, v in PRESET_DESCRIPTIONS.items()
    ]


@router.get("", response_model=List[ScenarioResponse])
async def list_scenarios(session: Session = Depends(get_session)):
    scenarios = session.exec(select(Scenario)).all()
    return [
        ScenarioResponse(
            id=s.id,
            name=s.name,
            description=s.description,
            preset=s.preset,
            dataset_id=s.dataset_id,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in scenarios
    ]


@router.post("", response_model=ScenarioResponse)
async def create_scenario(body: ScenarioCreate, session: Session = Depends(get_session)):
    if body.dataset_id:
        ds = session.get(Dataset, body.dataset_id)
        if not ds:
            raise HTTPException(status_code=404, detail="Dataset not found.")

    scenario = Scenario(
        name=body.name,
        description=body.description or PRESET_DESCRIPTIONS.get(body.preset or "", ""),
        preset=body.preset,
        dataset_id=body.dataset_id,
        battery_config_json=body.battery.model_dump_json() if body.battery else None,
        tariff_config_json=body.tariff.model_dump_json() if body.tariff else None,
        grid_config_json=body.grid.model_dump_json() if body.grid else None,
        ev_config_json=body.ev.model_dump_json() if body.ev else None,
    )
    session.add(scenario)
    session.commit()
    session.refresh(scenario)

    return ScenarioResponse(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        preset=scenario.preset,
        dataset_id=scenario.dataset_id,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
    )


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str, session: Session = Depends(get_session)):
    s = session.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "preset": s.preset,
        "dataset_id": s.dataset_id,
        "battery_config": json.loads(s.battery_config_json) if s.battery_config_json else None,
        "tariff_config": json.loads(s.tariff_config_json) if s.tariff_config_json else None,
        "grid_config": json.loads(s.grid_config_json) if s.grid_config_json else None,
        "ev_config": json.loads(s.ev_config_json) if s.ev_config_json else None,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


@router.put("/{scenario_id}")
async def update_scenario(
    scenario_id: str, body: ScenarioCreate, session: Session = Depends(get_session)
):
    s = session.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    s.name = body.name
    s.description = body.description
    s.preset = body.preset
    s.battery_config_json = body.battery.model_dump_json() if body.battery else s.battery_config_json
    s.tariff_config_json = body.tariff.model_dump_json() if body.tariff else s.tariff_config_json
    s.grid_config_json = body.grid.model_dump_json() if body.grid else s.grid_config_json
    s.ev_config_json = body.ev.model_dump_json() if body.ev else s.ev_config_json
    s.updated_at = datetime.utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)

    return {"message": "Scenario updated.", "id": s.id}


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: str, session: Session = Depends(get_session)):
    s = session.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    session.delete(s)
    session.commit()
    return {"message": "Scenario deleted."}
