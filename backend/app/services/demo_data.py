"""
Demo data generator for EnerShare AI.
Produces a deterministic, realistic 30-day MSME energy dataset.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json


# ── Reproducible seed for determinism ──────────────────────────────────────
RNG_SEED = 42
rng = np.random.default_rng(RNG_SEED)


def _solar_curve(hour: float, capacity_kw: float = 50.0) -> float:
    """Simple bell-curve solar generation profile (kWh per hour interval)."""
    if hour < 6 or hour >= 19:
        return 0.0
    # Peak near solar noon ~12:30
    peak_hour = 12.5
    sigma = 3.0
    raw = np.exp(-0.5 * ((hour - peak_hour) / sigma) ** 2)
    return round(raw * capacity_kw, 4)


def _demand_curve(hour: int, day_of_week: int, base_kw: float = 30.0) -> float:
    """MSME demand profile: higher during working hours Mon-Sat."""
    is_weekday = day_of_week < 6  # 0=Monday
    if not is_weekday:
        base_kw *= 0.3  # Minimal weekend demand
    if 0 <= hour < 6:
        factor = 0.15
    elif 6 <= hour < 9:
        factor = 0.5
    elif 9 <= hour < 18:
        factor = 1.0
    elif 18 <= hour < 21:
        factor = 0.6
    else:
        factor = 0.2
    return round(base_kw * factor, 4)


def _weather_factor(day_of_year: int, cloud_cover_pct: float) -> float:
    """Irradiance factor based on season and clouds."""
    seasonal = 0.7 + 0.3 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
    cloud_factor = 1.0 - 0.7 * (cloud_cover_pct / 100.0)
    return seasonal * cloud_factor


def generate_demo_dataset(
    start_date: str = "2024-01-01",
    days: int = 30,
    solar_capacity_kw: float = 50.0,
    demand_base_kw: float = 30.0,
    interval_hours: float = 1.0,
) -> pd.DataFrame:
    """
    Generate a deterministic demo dataset for 'days' days at hourly intervals.
    Returns a DataFrame with the required columns.
    """
    rng_local = np.random.default_rng(RNG_SEED)
    start = datetime.strptime(start_date, "%Y-%m-%d")
    records = []

    for day_offset in range(days):
        dt_day = start + timedelta(days=day_offset)
        day_of_week = dt_day.weekday()
        day_of_year = dt_day.timetuple().tm_yday

        # Daily cloud variation (0–100%)
        base_cloud = 20 + 60 * rng_local.random()  # 20-80% range
        cloud_variation = rng_local.normal(0, 10, 24)

        for h in range(int(24 / interval_hours)):
            hour = h * interval_hours
            ts = dt_day + timedelta(hours=hour)

            cloud_pct = float(np.clip(base_cloud + cloud_variation[h], 0, 100))
            temp_c = float(25 + 10 * np.sin(2 * np.pi * (hour - 6) / 24)
                          + rng_local.normal(0, 1))
            irradiance = float(max(0, 1000 * _solar_curve(hour, 1.0) / solar_capacity_kw
                                  * _weather_factor(day_of_year, cloud_pct)
                                  if _solar_curve(hour, 1.0) > 0 else 0))
            irradiance = min(irradiance, 1200)

            solar_raw = _solar_curve(hour, solar_capacity_kw)
            solar_factor = _weather_factor(day_of_year, cloud_pct)
            solar_kwh = round(solar_raw * solar_factor * interval_hours
                             + rng_local.normal(0, 0.3), 4)
            solar_kwh = max(0.0, solar_kwh)

            demand_raw = _demand_curve(int(hour), day_of_week, demand_base_kw)
            demand_kwh = round(demand_raw * interval_hours
                              + rng_local.normal(0, 0.5), 4)
            demand_kwh = max(0.1, demand_kwh)

            # Import tariff: time-of-use structure
            if 6 <= hour < 9 or 18 <= hour < 22:
                import_tariff = 10.5  # Peak
            elif 22 <= hour or hour < 6:
                import_tariff = 5.5   # Off-peak
            else:
                import_tariff = 8.5   # Normal

            records.append({
                "timestamp": ts.isoformat(),
                "solar_kwh": solar_kwh,
                "wind_kwh": 0.0,
                "demand_kwh": demand_kwh,
                "irradiance_wm2": round(irradiance, 2),
                "temperature_c": round(temp_c, 2),
                "cloud_cover_pct": round(cloud_pct, 2),
                "wind_speed_ms": 0.0,
                "import_tariff_inr_kwh": import_tariff,
                "export_tariff_inr_kwh": 3.0,
                "data_quality": "simulated",
            })

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def get_demo_records_as_list(days: int = 30) -> List[Dict[str, Any]]:
    """Return demo data as a list of dicts (JSON-serializable)."""
    df = generate_demo_dataset(days=days)
    records = []
    for _, row in df.iterrows():
        records.append({
            "timestamp": row["timestamp"].isoformat(),
            "solar_kwh": float(row["solar_kwh"]),
            "wind_kwh": float(row["wind_kwh"]),
            "demand_kwh": float(row["demand_kwh"]),
            "irradiance_wm2": float(row["irradiance_wm2"]),
            "temperature_c": float(row["temperature_c"]),
            "cloud_cover_pct": float(row["cloud_cover_pct"]),
            "wind_speed_ms": float(row["wind_speed_ms"]),
            "import_tariff_inr_kwh": float(row["import_tariff_inr_kwh"]),
            "export_tariff_inr_kwh": float(row["export_tariff_inr_kwh"]),
            "data_quality": row["data_quality"],
        })
    return records


def get_scenario_slice(
    preset: str,
    hours: int = 24,
    solar_capacity_kw: float = 50.0,
    demand_base_kw: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Return a 24-hour tailored slice for each preset scenario.
    This is used when the optimizer runs a named preset.
    """
    rng_local = np.random.default_rng(RNG_SEED + hash(preset) % 1000)
    ts_base = datetime(2024, 6, 15)  # sunny mid-year day
    records = []

    for h in range(hours):
        ts = ts_base + timedelta(hours=h)
        solar_base = _solar_curve(h, solar_capacity_kw)
        demand_base = _demand_curve(h, 1, demand_base_kw)  # Tuesday

        if preset == "solar_surplus":
            solar = solar_base * 1.4
            demand = demand_base * 0.6
            cloud = 5.0
        elif preset == "deficit":
            solar = solar_base * 0.3
            demand = demand_base * 1.5
            cloud = 80.0
        elif preset == "low_battery":
            solar = solar_base * 0.9
            demand = demand_base
            cloud = 20.0
        elif preset == "high_tariff":
            solar = solar_base * 0.8
            demand = demand_base * 1.1
            cloud = 30.0
        elif preset == "export_disabled":
            solar = solar_base * 1.5
            demand = demand_base * 0.5
            cloud = 5.0
        elif preset == "ev_demand":
            solar = solar_base
            demand = demand_base
            cloud = 20.0
        elif preset == "cloudy":
            solar = solar_base * 0.2
            demand = demand_base
            cloud = 90.0
        elif preset == "battery_full":
            solar = solar_base * 1.2
            demand = demand_base * 0.8
            cloud = 10.0
        else:
            solar = solar_base
            demand = demand_base
            cloud = 20.0

        solar = max(0.0, float(solar) + rng_local.normal(0, 0.2))
        demand = max(0.1, float(demand) + rng_local.normal(0, 0.3))

        if 6 <= h < 9 or 18 <= h < 22:
            tariff = 10.5
        elif 22 <= h or h < 6:
            tariff = 5.5
        else:
            tariff = 8.5

        records.append({
            "timestamp": ts.isoformat(),
            "solar_kwh": round(solar, 4),
            "wind_kwh": 0.0,
            "demand_kwh": round(demand, 4),
            "irradiance_wm2": round(max(0, 900 * (solar / solar_capacity_kw)) if solar_capacity_kw else 0, 2),
            "temperature_c": round(28 + 8 * np.sin(2 * np.pi * (h - 6) / 24), 2),
            "cloud_cover_pct": round(cloud, 2),
            "wind_speed_ms": 0.0,
            "import_tariff_inr_kwh": tariff,
            "export_tariff_inr_kwh": 3.0,
            "data_quality": "simulated",
        })

    return records
