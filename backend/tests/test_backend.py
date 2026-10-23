"""Automated test suite for EnerShare AI backend."""
import sys
import os
sys.path.insert(0, os.path.abspath("."))
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from app.services.demo_data import generate_demo_dataset, get_demo_records_as_list
from app.ml.forecaster import EnerShareForecaster
from app.optimization.optimizer import (
    optimize_lp, run_baseline, BatteryParams, GridParams, EVParams
)


def test_demo_data_generation():
    df = generate_demo_dataset(days=7)
    assert len(df) == 7 * 24
    assert "timestamp" in df.columns
    assert "solar_kwh" in df.columns
    assert "demand_kwh" in df.columns
    assert (df["solar_kwh"] >= 0).all()
    assert (df["demand_kwh"] >= 0).all()


def test_forecaster_fit_predict():
    df = generate_demo_dataset(days=14)
    forecaster = EnerShareForecaster(target="solar_kwh", model_name="xgboost")
    fit_metrics = forecaster.fit(df)
    assert "val_mae" in fit_metrics
    assert "val_rmse" in fit_metrics
    assert fit_metrics["status"] in ("trained", "baseline_fallback")

    preds, warnings = forecaster.predict(df, horizon=24)
    assert len(preds) == 24
    assert all(isinstance(p, (float, int, np.floating)) for p in preds)
    assert all(p >= 0 for p in preds)


def test_optimizer_constraints():
    """Verify that optimizer respects battery, grid, and conservation bounds."""
    now = datetime(2026, 10, 23, 0, 0)
    timestamps = [now + timedelta(hours=i) for i in range(24)]
    
    # 24-hour profile: high solar midday, high demand evening
    generation = [
        0, 0, 0, 0, 0, 1.2, 5.5, 14.2, 22.1, 28.4, 32.0, 31.5,
        28.0, 21.0, 12.5, 4.0, 0.5, 0, 0, 0, 0, 0, 0, 0
    ]
    demand = [
        8.0, 7.5, 7.0, 7.0, 8.5, 12.0, 18.0, 20.0, 22.0, 21.0, 20.0, 19.0,
        18.0, 19.5, 21.0, 24.0, 28.0, 30.0, 26.0, 22.0, 18.0, 14.0, 11.0, 9.0
    ]
    import_tariffs = [8.5] * 24
    for h in range(18, 23):
        import_tariffs[h] = 12.0  # Evening peak tariff

    battery = BatteryParams(
        capacity_kwh=100.0,
        min_soc_pct=20.0,
        max_soc_pct=95.0,
        initial_soc_pct=50.0,
        charge_power_kw=25.0,
        discharge_power_kw=25.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
    )
    grid = GridParams(
        import_limit_kw=50.0,
        export_limit_kw=25.0,
        export_permitted=False,
    )
    ev = EVParams(enabled=False)

    result = optimize_lp(
        generation_kwh=generation,
        demand_kwh=demand,
        timestamps=timestamps,
        import_tariffs=import_tariffs,
        battery=battery,
        grid=grid,
        ev=ev,
    )

    assert result.status in ("optimal", "fallback")
    assert len(result.schedule) == 24

    for ir in result.schedule:
        # 1. Battery SOC within bounds (allow small float epsilon)
        assert ir.battery_soc_pct >= battery.min_soc_pct - 0.05
        assert ir.battery_soc_pct <= battery.max_soc_pct + 0.05

        # 2. Charge/discharge power limits
        assert ir.battery_charge_kwh <= battery.charge_power_kw + 0.05
        assert ir.battery_discharge_kwh <= battery.discharge_power_kw + 0.05

        # 3. Grid limits
        assert ir.grid_import_kwh <= grid.import_limit_kw + 0.05
        if not grid.export_permitted:
            assert ir.grid_export_kwh <= 0.001

        # 4. Energy balance check:
        # renewable_used + battery_charge + grid_export + curtailed == renewable_gen
        total_gen_allocated = ir.renewable_used_kwh + ir.battery_charge_kwh + ir.grid_export_kwh + ir.curtailed_kwh
        assert abs(total_gen_allocated - ir.renewable_gen_kwh) < 0.1, (
            f"Gen mismatch at interval {ir.interval}: allocated {total_gen_allocated} vs gen {ir.renewable_gen_kwh}"
        )


def test_baseline_vs_optimizer():
    """Verify that optimization achieves equal or better cost than heuristic baseline."""
    now = datetime(2026, 10, 23, 0, 0)
    timestamps = [now + timedelta(hours=i) for i in range(24)]
    generation = [0, 0, 0, 0, 0, 2, 8, 16, 24, 30, 32, 30, 25, 18, 10, 3, 0, 0, 0, 0, 0, 0, 0, 0]
    demand = [10, 10, 10, 10, 12, 15, 20, 22, 22, 20, 18, 18, 18, 20, 22, 25, 30, 32, 28, 24, 18, 14, 12, 10]
    import_tariffs = [7.0] * 24
    for h in range(17, 23):
        import_tariffs[h] = 13.0  # Big peak penalty

    battery = BatteryParams(capacity_kwh=100.0, initial_soc_pct=50.0)
    grid = GridParams(import_limit_kw=100.0, export_permitted=False)
    ev = EVParams(enabled=False)

    opt_result = optimize_lp(
        generation_kwh=generation,
        demand_kwh=demand,
        timestamps=timestamps,
        import_tariffs=import_tariffs,
        battery=battery,
        grid=grid,
        ev=ev,
    )

    base_result = run_baseline(
        generation_kwh=generation,
        demand_kwh=demand,
        timestamps=timestamps,
        import_tariffs=import_tariffs,
        battery=battery,
        grid=grid,
        ev=ev,
    )

    assert opt_result.status in ("optimal", "fallback")
    assert base_result.status == "baseline_complete"
    # Optimization should save cost or equal baseline
    assert opt_result.total_cost_inr <= base_result.total_cost_inr + 1.0


if __name__ == "__main__":
    test_demo_data_generation()
    print("[PASS] Demo data generation passed")
    test_forecaster_fit_predict()
    print("[PASS] Forecaster fit & predict passed")
    test_optimizer_constraints()
    print("[PASS] Optimizer constraints passed")
    test_baseline_vs_optimizer()
    print("[PASS] Baseline vs optimizer comparison passed")
    print("ALL TESTS PASSED SUCCESSFULLY!")
