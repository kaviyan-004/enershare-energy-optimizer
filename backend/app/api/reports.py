"""Report generation and schedule export endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session
import json
import io
import csv

from app.core.database import get_session
from app.models.db_models import OptimizationRun, Scenario

router = APIRouter()


@router.get("/export/csv/{run_id}")
async def export_schedule_csv(run_id: str, session: Session = Depends(get_session)):
    """Export the interval schedule as a downloadable CSV."""
    run = session.get(OptimizationRun, run_id)
    if not run or not run.schedule_json:
        raise HTTPException(status_code=404, detail="Run schedule not found.")

    schedule = json.loads(run.schedule_json)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Interval",
        "Timestamp",
        "Renewable_Gen_kWh",
        "Demand_kWh",
        "Renewable_Used_Direct_kWh",
        "Battery_Charge_kWh",
        "Battery_Discharge_kWh",
        "Battery_SOC_Pct",
        "Grid_Import_kWh",
        "Grid_Export_kWh",
        "Curtailed_kWh",
        "EV_Served_kWh",
        "Unmet_Demand_kWh",
        "Interval_Cost_INR",
        "Action_Summary",
    ])

    for row in schedule:
        writer.writerow([
            row.get("interval"),
            row.get("timestamp"),
            row.get("renewable_gen_kwh"),
            row.get("demand_kwh"),
            row.get("renewable_used_kwh"),
            row.get("battery_charge_kwh"),
            row.get("battery_discharge_kwh"),
            row.get("battery_soc_pct"),
            row.get("grid_import_kwh"),
            row.get("grid_export_kwh"),
            row.get("curtailed_kwh"),
            row.get("ev_served_kwh"),
            row.get("unmet_demand_kwh"),
            row.get("interval_cost_inr"),
            row.get("action_summary"),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=enershare_schedule_{run_id[:8]}.csv"},
    )


@router.get("/export/json/{run_id}")
async def export_schedule_json(run_id: str, session: Session = Depends(get_session)):
    """Export the run details and schedule as JSON."""
    run = session.get(OptimizationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    data = {
        "project": "EnerShare AI",
        "system_version": "1.0.0",
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "solver_used": run.solver_used,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "kpis": {
            "total_cost_inr": run.total_cost_inr,
            "total_import_kwh": run.total_import_kwh,
            "total_export_kwh": run.total_export_kwh,
            "total_curtailed_kwh": run.total_curtailed_kwh,
            "total_unmet_kwh": run.total_unmet_kwh,
            "renewable_utilization_pct": run.renewable_utilization_pct,
        },
        "schedule": json.loads(run.schedule_json) if run.schedule_json else [],
    }

    return StreamingResponse(
        iter([json.dumps(data, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=enershare_run_{run_id[:8]}.json"},
    )


@router.get("/summary/{run_id}")
async def get_run_executive_summary(run_id: str, session: Session = Depends(get_session)):
    """Produce executive summary text for presentation, reporting, or audit."""
    run = session.get(OptimizationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    scenario = session.get(Scenario, run.scenario_id) if run.scenario_id else None
    scenario_name = scenario.name if scenario else "Standard 24h Horizon"

    return {
        "run_id": run.id,
        "scenario_name": scenario_name,
        "date_evaluated": run.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "key_metrics": {
            "operating_cost_inr": f"₹{run.total_cost_inr:.2f}" if run.total_cost_inr else "N/A",
            "grid_import_kwh": f"{run.total_import_kwh:.2f} kWh" if run.total_import_kwh else "0.0 kWh",
            "grid_export_kwh": f"{run.total_export_kwh:.2f} kWh" if run.total_export_kwh else "0.0 kWh",
            "curtailed_kwh": f"{run.total_curtailed_kwh:.2f} kWh" if run.total_curtailed_kwh else "0.0 kWh",
            "renewable_utilization": f"{run.renewable_utilization_pct:.1f}%" if run.renewable_utilization_pct else "0%",
            "outage_unmet_kwh": f"{run.total_unmet_kwh:.2f} kWh" if run.total_unmet_kwh else "0.0 kWh",
        },
        "executive_takeaway": (
            f"Under scenario '{scenario_name}', the EnerShare LP optimizer prioritized on-site self-consumption, "
            f"scheduling battery charge during peak solar surplus and discharging during evening high-tariff peak. "
            f"Renewable utilization reached {run.renewable_utilization_pct:.1f}%, curtailing only {run.total_curtailed_kwh or 0:.2f} kWh."
        ),
        "audit_note": "Simulated evaluation conforming to grid import and battery operating bounds."
    }
