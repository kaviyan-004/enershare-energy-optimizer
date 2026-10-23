"""Optimization API endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List, Optional, Dict, Any
import json
from datetime import datetime, timedelta
import pandas as pd

from app.core.database import get_session
from app.models.db_models import Scenario, Dataset, OptimizationRun, BaselineRun, ComparisonResult, SiteConfig
from app.models.schemas import (
    OptimizeRequest, OptimizationResponse, BaselineResponse, ComparisonResponse,
    IntervalSchedule, KPISummary, BatteryConfig, GridConfig, TariffConfig, EVConfig
)
from app.optimization.optimizer import (
    optimize_lp, run_baseline, BatteryParams, GridParams, EVParams, OptimizationResult
)
from app.services.demo_data import generate_demo_dataset

router = APIRouter()


def _get_scenario_data(scenario: Scenario, body: OptimizeRequest, session: Session):
    """Extract generation, demand, timestamps, and parameters for optimization."""
    # 1. Base parameters from scenario or site config
    site = session.exec(select(SiteConfig)).first()
    if not site:
        site = SiteConfig()
        session.add(site)
        session.commit()
        session.refresh(site)

    # Battery
    if scenario.battery_config_json:
        bat_dict = json.loads(scenario.battery_config_json)
        battery = BatteryParams(**bat_dict)
    else:
        battery = BatteryParams(
            capacity_kwh=site.battery_capacity_kwh,
            min_soc_pct=site.battery_min_soc_pct,
            max_soc_pct=site.battery_max_soc_pct,
            initial_soc_pct=site.battery_initial_soc_pct,
            charge_power_kw=site.battery_charge_power_kw,
            discharge_power_kw=site.battery_discharge_power_kw,
            charge_efficiency=site.battery_charge_efficiency,
            discharge_efficiency=site.battery_discharge_efficiency,
            reserve_pct=site.battery_reserve_pct,
        )

    # Grid
    if scenario.grid_config_json:
        grid_dict = json.loads(scenario.grid_config_json)
        grid = GridParams(**grid_dict)
    else:
        grid = GridParams(
            import_limit_kw=site.grid_import_limit_kw,
            export_limit_kw=site.grid_export_limit_kw,
            export_permitted=site.export_permitted,
        )

    # EV
    if scenario.ev_config_json:
        ev_dict = json.loads(scenario.ev_config_json)
        ev = EVParams(**ev_dict)
    else:
        ev = EVParams(
            enabled=site.ev_charger_enabled,
            charger_power_kw=site.ev_charger_power_kw,
            daily_demand_kwh=site.ev_daily_demand_kwh,
        )

    # Tariffs
    tariff_import = site.import_tariff_inr_kwh
    tariff_export = site.export_tariff_inr_kwh
    if scenario.tariff_config_json:
        t_dict = json.loads(scenario.tariff_config_json)
        tariff_import = t_dict.get("import_tariff_inr_kwh", tariff_import)
        tariff_export = t_dict.get("export_tariff_inr_kwh", tariff_export)
        if "export_permitted" in t_dict:
            grid.export_permitted = t_dict["export_permitted"]

    # Profile generation
    horizon = 24
    interval_hours = 1.0

    # Explicit overrides in request
    if body.generation_kwh and body.demand_kwh:
        n = min(len(body.generation_kwh), len(body.demand_kwh))
        gen_profile = [float(x) for x in body.generation_kwh[:n]]
        dem_profile = [float(x) for x in body.demand_kwh[:n]]
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        timestamps = [now + timedelta(hours=i) for i in range(n)]
    else:
        # Load from dataset if attached, otherwise synthetic demo
        df = None
        if scenario.dataset_id:
            ds = session.get(Dataset, scenario.dataset_id)
            if ds and ds.source != "demo":
                from app.core.config import settings
                import os
                p = settings.uploads_dir / f"{ds.id}.csv"
                if os.path.exists(p):
                    df = pd.read_csv(p)
                    df["timestamp"] = pd.to_datetime(df["timestamp"])

        if df is None:
            df = generate_demo_dataset(days=2)

        # Take last 24 records
        df_slice = df.tail(horizon).copy()
        gen_profile = df_slice["solar_kwh"].tolist()
        dem_profile = df_slice["demand_kwh"].tolist()
        timestamps = [pd.to_datetime(t).to_pydatetime() for t in df_slice["timestamp"]]

    # Preset adjustments
    if scenario.preset == "solar_surplus":
        gen_profile = [g * 2.2 for g in gen_profile]
    elif scenario.preset == "deficit":
        gen_profile = [g * 0.25 for g in gen_profile]
        dem_profile = [d * 1.3 for d in dem_profile]
    elif scenario.preset == "low_battery":
        battery.initial_soc_pct = 20.0
    elif scenario.preset == "battery_full":
        battery.initial_soc_pct = 95.0
    elif scenario.preset == "high_tariff":
        tariff_import = tariff_import * 1.8
    elif scenario.preset == "export_disabled":
        grid.export_permitted = False
    elif scenario.preset == "ev_demand":
        ev.enabled = True
        ev.daily_demand_kwh = 45.0
    elif scenario.preset == "cloudy":
        gen_profile = [g * 0.4 for g in gen_profile]

    import_tariffs = [tariff_import] * len(gen_profile)
    # Apply Time-of-Day pricing variation: Peak hours (18-22) +30%, Off-peak (23-06) -20%
    for i, ts in enumerate(timestamps):
        h = ts.hour
        if 18 <= h <= 22:
            import_tariffs[i] = tariff_import * 1.35
        elif 23 <= h or h <= 5:
            import_tariffs[i] = tariff_import * 0.80

    return {
        "generation": gen_profile,
        "demand": dem_profile,
        "timestamps": timestamps,
        "import_tariffs": import_tariffs,
        "export_tariff": tariff_export,
        "battery": battery,
        "grid": grid,
        "ev": ev,
        "interval_hours": interval_hours,
    }


@router.post("", response_model=OptimizationResponse)
async def run_optimization(body: OptimizeRequest, session: Session = Depends(get_session)):
    """Run constrained LP optimization on a scenario and save results."""
    scenario = session.get(Scenario, body.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    data = _get_scenario_data(scenario, body, session)

    opt_result: OptimizationResult = optimize_lp(
        generation_kwh=data["generation"],
        demand_kwh=data["demand"],
        timestamps=data["timestamps"],
        import_tariffs=data["import_tariffs"],
        battery=data["battery"],
        grid=data["grid"],
        ev=data["ev"],
        interval_hours=data["interval_hours"],
        export_tariff=data["export_tariff"],
    )

    schedules_data = [ir.to_dict() for ir in opt_result.schedule]

    run = OptimizationRun(
        scenario_id=scenario.id,
        solver_used=opt_result.solver_used,
        status="done" if opt_result.status in ("optimal", "fallback") else "error",
        objective_value=opt_result.objective_value,
        total_cost_inr=opt_result.total_cost_inr,
        total_import_kwh=opt_result.total_import_kwh,
        total_export_kwh=opt_result.total_export_kwh,
        total_curtailed_kwh=opt_result.total_curtailed_kwh,
        total_unmet_kwh=opt_result.total_unmet_kwh,
        renewable_utilization_pct=opt_result.renewable_utilization_pct,
        schedule_json=json.dumps(schedules_data),
        warnings=json.dumps(opt_result.warnings),
        error_message=opt_result.error_message,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    # Convert schedule to Pydantic IntervalSchedule
    schedule_pydantic = [
        IntervalSchedule(
            interval=s["interval"],
            timestamp=datetime.fromisoformat(s["timestamp"]),
            renewable_gen_kwh=s["renewable_gen_kwh"],
            demand_kwh=s["demand_kwh"],
            renewable_used_kwh=s["renewable_used_kwh"],
            battery_charge_kwh=s["battery_charge_kwh"],
            battery_discharge_kwh=s["battery_discharge_kwh"],
            battery_soc_pct=s["battery_soc_pct"],
            grid_import_kwh=s["grid_import_kwh"],
            grid_export_kwh=s["grid_export_kwh"],
            curtailed_kwh=s["curtailed_kwh"],
            ev_served_kwh=s["ev_served_kwh"],
            unmet_demand_kwh=s["unmet_demand_kwh"],
            interval_cost_inr=s["interval_cost_inr"],
            action_summary=s["action_summary"],
            constraint_notes=s["constraint_notes"],
        )
        for s in schedules_data
    ]

    return OptimizationResponse(
        run_id=run.id,
        status=run.status,
        solver=opt_result.solver_used,
        objective_value=opt_result.objective_value,
        total_cost_inr=opt_result.total_cost_inr,
        total_import_kwh=opt_result.total_import_kwh,
        total_export_kwh=opt_result.total_export_kwh,
        total_curtailed_kwh=opt_result.total_curtailed_kwh,
        total_unmet_kwh=opt_result.total_unmet_kwh,
        renewable_utilization_pct=opt_result.renewable_utilization_pct,
        schedule=schedule_pydantic,
        recommendation=opt_result.recommendation,
        warnings=opt_result.warnings,
        error_message=opt_result.error_message,
    )


@router.post("/baseline", response_model=BaselineResponse)
async def run_baseline_endpoint(body: OptimizeRequest, session: Session = Depends(get_session)):
    """Run baseline heuristic priority dispatch for scenario comparison."""
    scenario = session.get(Scenario, body.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    data = _get_scenario_data(scenario, body, session)

    base_result: OptimizationResult = run_baseline(
        generation_kwh=data["generation"],
        demand_kwh=data["demand"],
        timestamps=data["timestamps"],
        import_tariffs=data["import_tariffs"],
        battery=data["battery"],
        grid=data["grid"],
        ev=data["ev"],
        interval_hours=data["interval_hours"],
        export_tariff=data["export_tariff"],
    )

    schedules_data = [ir.to_dict() for ir in base_result.schedule]

    brun = BaselineRun(
        scenario_id=scenario.id,
        strategy="simple_priority",
        status="done",
        total_cost_inr=base_result.total_cost_inr,
        total_import_kwh=base_result.total_import_kwh,
        total_export_kwh=base_result.total_export_kwh,
        total_curtailed_kwh=base_result.total_curtailed_kwh,
        total_unmet_kwh=base_result.total_unmet_kwh,
        renewable_utilization_pct=base_result.renewable_utilization_pct,
        schedule_json=json.dumps(schedules_data),
    )
    session.add(brun)
    session.commit()
    session.refresh(brun)

    schedule_pydantic = [
        IntervalSchedule(
            interval=s["interval"],
            timestamp=datetime.fromisoformat(s["timestamp"]),
            renewable_gen_kwh=s["renewable_gen_kwh"],
            demand_kwh=s["demand_kwh"],
            renewable_used_kwh=s["renewable_used_kwh"],
            battery_charge_kwh=s["battery_charge_kwh"],
            battery_discharge_kwh=s["battery_discharge_kwh"],
            battery_soc_pct=s["battery_soc_pct"],
            grid_import_kwh=s["grid_import_kwh"],
            grid_export_kwh=s["grid_export_kwh"],
            curtailed_kwh=s["curtailed_kwh"],
            ev_served_kwh=s["ev_served_kwh"],
            unmet_demand_kwh=s["unmet_demand_kwh"],
            interval_cost_inr=s["interval_cost_inr"],
            action_summary=s["action_summary"],
            constraint_notes=s["constraint_notes"],
        )
        for s in schedules_data
    ]

    return BaselineResponse(
        run_id=brun.id,
        strategy=brun.strategy,
        total_cost_inr=round(base_result.total_cost_inr, 2),
        total_import_kwh=round(base_result.total_import_kwh, 2),
        total_export_kwh=round(base_result.total_export_kwh, 2),
        total_curtailed_kwh=round(base_result.total_curtailed_kwh, 2),
        total_unmet_kwh=round(base_result.total_unmet_kwh, 2),
        renewable_utilization_pct=round(base_result.renewable_utilization_pct, 1),
        schedule=schedule_pydantic,
    )


@router.post("/compare", response_model=ComparisonResponse)
async def compare_runs(body: OptimizeRequest, session: Session = Depends(get_session)):
    """Run both LP optimization and Baseline to produce comparative metrics."""
    scenario = session.get(Scenario, body.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    data = _get_scenario_data(scenario, body, session)

    # 1. Run Optimized
    opt_result = optimize_lp(
        generation_kwh=data["generation"],
        demand_kwh=data["demand"],
        timestamps=data["timestamps"],
        import_tariffs=data["import_tariffs"],
        battery=data["battery"],
        grid=data["grid"],
        ev=data["ev"],
        interval_hours=data["interval_hours"],
        export_tariff=data["export_tariff"],
    )

    # 2. Run Baseline
    base_result = run_baseline(
        generation_kwh=data["generation"],
        demand_kwh=data["demand"],
        timestamps=data["timestamps"],
        import_tariffs=data["import_tariffs"],
        battery=data["battery"],
        grid=data["grid"],
        ev=data["ev"],
        interval_hours=data["interval_hours"],
        export_tariff=data["export_tariff"],
    )

    # Save runs
    opt_run = OptimizationRun(
        scenario_id=scenario.id,
        solver_used=opt_result.solver_used,
        status="done",
        objective_value=opt_result.objective_value,
        total_cost_inr=opt_result.total_cost_inr,
        total_import_kwh=opt_result.total_import_kwh,
        total_export_kwh=opt_result.total_export_kwh,
        total_curtailed_kwh=opt_result.total_curtailed_kwh,
        total_unmet_kwh=opt_result.total_unmet_kwh,
        renewable_utilization_pct=opt_result.renewable_utilization_pct,
        schedule_json=json.dumps([ir.to_dict() for ir in opt_result.schedule]),
    )
    base_run = BaselineRun(
        scenario_id=scenario.id,
        strategy="simple_priority",
        status="done",
        total_cost_inr=base_result.total_cost_inr,
        total_import_kwh=base_result.total_import_kwh,
        total_export_kwh=base_result.total_export_kwh,
        total_curtailed_kwh=base_result.total_curtailed_kwh,
        total_unmet_kwh=base_result.total_unmet_kwh,
        renewable_utilization_pct=base_result.renewable_utilization_pct,
        schedule_json=json.dumps([ir.to_dict() for ir in base_result.schedule]),
    )
    session.add(opt_run)
    session.add(base_run)
    session.commit()
    session.refresh(opt_run)
    session.refresh(base_run)

    # Compute savings
    opt_cost = opt_result.total_cost_inr
    base_cost = base_result.total_cost_inr
    saving_inr = base_cost - opt_cost
    saving_pct = (saving_inr / base_cost * 100.0) if base_cost > 0.01 else 0.0

    imp_red_kwh = base_result.total_import_kwh - opt_result.total_import_kwh
    curt_diff_kwh = base_result.total_curtailed_kwh - opt_result.total_curtailed_kwh
    util_diff_pct = opt_result.renewable_utilization_pct - base_result.renewable_utilization_pct

    comp = ComparisonResult(
        optimization_run_id=opt_run.id,
        baseline_run_id=base_run.id,
        cost_saving_inr=saving_inr,
        cost_saving_pct=saving_pct,
        import_reduction_kwh=imp_red_kwh,
        curtailment_change_kwh=curt_diff_kwh,
        renewable_util_improvement_pct=util_diff_pct,
    )
    session.add(comp)
    session.commit()

    comparison_table = [
        {
            "metric": "Operating Energy Cost (₹)",
            "baseline": round(base_cost, 2),
            "optimized": round(opt_cost, 2),
            "delta": round(-saving_inr, 2),
            "unit": "₹",
            "better": "lower"
        },
        {
            "metric": "Grid Electricity Imported",
            "baseline": round(base_result.total_import_kwh, 2),
            "optimized": round(opt_result.total_import_kwh, 2),
            "delta": round(-imp_red_kwh, 2),
            "unit": "kWh",
            "better": "lower"
        },
        {
            "metric": "Renewable Self-Consumption",
            "baseline": round(base_result.renewable_utilization_pct, 1),
            "optimized": round(opt_result.renewable_utilization_pct, 1),
            "delta": round(util_diff_pct, 1),
            "unit": "%",
            "better": "higher"
        },
        {
            "metric": "Renewable Curtailed (Wasted)",
            "baseline": round(base_result.total_curtailed_kwh, 2),
            "optimized": round(opt_result.total_curtailed_kwh, 2),
            "delta": round(-curt_diff_kwh, 2),
            "unit": "kWh",
            "better": "lower"
        },
        {
            "metric": "Unmet Demand (Outage Risk)",
            "baseline": round(base_result.total_unmet_kwh, 2),
            "optimized": round(opt_result.total_unmet_kwh, 2),
            "delta": round(opt_result.total_unmet_kwh - base_result.total_unmet_kwh, 2),
            "unit": "kWh",
            "better": "lower"
        },
    ]

    return ComparisonResponse(
        scenario_id=scenario.id,
        optimization_run_id=opt_run.id,
        baseline_run_id=base_run.id,
        optimized={
            "total_cost_inr": round(opt_cost, 2),
            "total_import_kwh": round(opt_result.total_import_kwh, 2),
            "total_export_kwh": round(opt_result.total_export_kwh, 2),
            "total_curtailed_kwh": round(opt_result.total_curtailed_kwh, 2),
            "renewable_utilization_pct": round(opt_result.renewable_utilization_pct, 1),
        },
        baseline={
            "total_cost_inr": round(base_cost, 2),
            "total_import_kwh": round(base_result.total_import_kwh, 2),
            "total_export_kwh": round(base_result.total_export_kwh, 2),
            "total_curtailed_kwh": round(base_result.total_curtailed_kwh, 2),
            "renewable_utilization_pct": round(base_result.renewable_utilization_pct, 1),
        },
        savings={
            "cost_saving_inr": round(saving_inr, 2),
            "cost_saving_pct": round(saving_pct, 1),
            "import_reduction_kwh": round(imp_red_kwh, 2),
            "curtailment_reduction_kwh": round(curt_diff_kwh, 2),
            "renewable_util_improvement_pct": round(util_diff_pct, 1),
        },
        comparison_table=comparison_table,
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: Session = Depends(get_session)):
    """Fetch stored optimization run and full schedule."""
    run = session.get(OptimizationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    schedule = json.loads(run.schedule_json) if run.schedule_json else []
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "solver_used": run.solver_used,
        "status": run.status,
        "total_cost_inr": run.total_cost_inr,
        "total_import_kwh": run.total_import_kwh,
        "total_export_kwh": run.total_export_kwh,
        "total_curtailed_kwh": run.total_curtailed_kwh,
        "total_unmet_kwh": run.total_unmet_kwh,
        "renewable_utilization_pct": run.renewable_utilization_pct,
        "schedule": schedule,
        "created_at": run.created_at,
    }


@router.get("/kpi", response_model=KPISummary)
async def get_kpi_summary(session: Session = Depends(get_session)):
    """Return dashboard KPI overview card metrics."""
    site = session.exec(select(SiteConfig)).first()
    site_name = site.name if site else "Demo Commercial Facility"

    # Get latest optimization run
    latest_run = session.exec(
        select(OptimizationRun).order_by(OptimizationRun.created_at.desc())
    ).first()

    if latest_run and latest_run.schedule_json:
        schedule = json.loads(latest_run.schedule_json)
        tot_gen = sum(r["renewable_gen_kwh"] for r in schedule)
        tot_dem = sum(r["demand_kwh"] for r in schedule)
        last_soc = schedule[-1]["battery_soc_pct"] if schedule else 50.0

        return KPISummary(
            site_name=site_name,
            data_mode="Optimized Schedule (Active)",
            last_calculation=latest_run.created_at,
            forecast_model_status="Trained (XGBoost)",
            optimization_status=f"Active ({latest_run.solver_used})",
            renewable_generation_kwh=round(tot_gen, 2),
            energy_demand_kwh=round(tot_dem, 2),
            battery_soc_pct=round(last_soc, 1),
            surplus_or_deficit_kwh=round(tot_gen - tot_dem, 2),
            grid_import_kwh=round(latest_run.total_import_kwh or 0.0, 2),
            grid_export_kwh=round(latest_run.total_export_kwh or 0.0, 2),
            renewable_utilization_pct=round(latest_run.renewable_utilization_pct or 0.0, 1),
            estimated_cost_inr=round(latest_run.total_cost_inr or 0.0, 2),
            forecast_mae=0.85,
            recommendation=(
                f"EnerShare AI scheduled {latest_run.total_import_kwh:.1f} kWh off-peak import "
                f"and achieved {latest_run.renewable_utilization_pct:.1f}% self-consumption."
            ),
            is_simulated=True,
        )

    # Fallback to simulated demo snapshot
    df = generate_demo_dataset(days=1)
    tot_gen = float(df["solar_kwh"].sum())
    tot_dem = float(df["demand_kwh"].sum())

    return KPISummary(
        site_name=site_name,
        data_mode="Demo Snapshot (Ready to Optimize)",
        last_calculation=datetime.utcnow(),
        forecast_model_status="Ready (XGBoost Available)",
        optimization_status="Ready to Run",
        renewable_generation_kwh=round(tot_gen, 2),
        energy_demand_kwh=round(tot_dem, 2),
        battery_soc_pct=50.0,
        surplus_or_deficit_kwh=round(tot_gen - tot_dem, 2),
        grid_import_kwh=round(max(0.0, tot_dem - tot_gen * 0.7), 2),
        grid_export_kwh=0.0,
        renewable_utilization_pct=78.5,
        estimated_cost_inr=round(max(0.0, tot_dem - tot_gen * 0.7) * 8.5, 2),
        forecast_mae=0.92,
        recommendation="Run optimization to evaluate constrained schedule and compute peak cost savings.",
        is_simulated=True,
    )
