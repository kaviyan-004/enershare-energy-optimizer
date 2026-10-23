"""SQLModel database models for EnerShare AI."""
from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
import uuid
import json


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ─── Dataset ──────────────────────────────────────────────────────────────────

class Dataset(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    name: str
    source: str  # "demo" | "upload" | "simulated"
    filename: Optional[str] = None
    row_count: int = 0
    start_timestamp: Optional[datetime] = None
    end_timestamp: Optional[datetime] = None
    interval_hours: float = 1.0
    has_solar: bool = True
    has_wind: bool = False
    has_weather: bool = False
    quality_warnings: Optional[str] = None  # JSON string
    created_at: datetime = Field(default_factory=datetime.utcnow)

    scenarios: List["Scenario"] = Relationship(back_populates="dataset")
    forecast_runs: List["ForecastRun"] = Relationship(back_populates="dataset")


# ─── Site & Assets ────────────────────────────────────────────────────────────

class SiteConfig(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    name: str = "Demo Commercial Facility"
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    solar_capacity_kw: float = 50.0
    wind_capacity_kw: float = 0.0
    has_wind: bool = False
    # Battery
    battery_capacity_kwh: float = 100.0
    battery_min_soc_pct: float = 20.0
    battery_max_soc_pct: float = 95.0
    battery_initial_soc_pct: float = 50.0
    battery_charge_power_kw: float = 25.0
    battery_discharge_power_kw: float = 25.0
    battery_charge_efficiency: float = 0.95
    battery_discharge_efficiency: float = 0.95
    battery_reserve_pct: float = 20.0
    # Grid
    grid_import_limit_kw: float = 100.0
    grid_export_limit_kw: float = 50.0
    export_permitted: bool = False
    # Tariff
    import_tariff_inr_kwh: float = 8.5
    export_tariff_inr_kwh: float = 3.0
    # EV / flexible load
    ev_charger_enabled: bool = False
    ev_charger_power_kw: float = 7.4
    ev_daily_demand_kwh: float = 30.0
    # Settings
    forecast_horizon_hours: int = 24
    interval_hours: float = 1.0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Scenario ─────────────────────────────────────────────────────────────────

class Scenario(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    name: str
    description: Optional[str] = None
    preset: Optional[str] = None  # "solar_surplus" | "deficit" etc.
    dataset_id: Optional[str] = Field(default=None, foreign_key="dataset.id")
    # Override parameters stored as JSON strings
    battery_config_json: Optional[str] = None
    tariff_config_json: Optional[str] = None
    generation_override_json: Optional[str] = None
    demand_override_json: Optional[str] = None
    ev_config_json: Optional[str] = None
    grid_config_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    dataset: Optional[Dataset] = Relationship(back_populates="scenarios")
    optimization_runs: List["OptimizationRun"] = Relationship(back_populates="scenario")
    baseline_runs: List["BaselineRun"] = Relationship(back_populates="scenario")


# ─── Forecast ─────────────────────────────────────────────────────────────────

class ForecastRun(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    dataset_id: str = Field(foreign_key="dataset.id")
    target: str  # "generation" | "demand"
    model_name: str  # "persistence" | "gradient_boost" | "xgboost"
    horizon_hours: int = 24
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None
    baseline_mae: Optional[float] = None
    baseline_rmse: Optional[float] = None
    feature_list: Optional[str] = None  # JSON
    warnings: Optional[str] = None  # JSON
    results_json: Optional[str] = None  # JSON array of {timestamp, actual, predicted}
    status: str = "pending"  # pending | running | done | error
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    dataset: Optional[Dataset] = Relationship(back_populates="forecast_runs")


# ─── Optimization ─────────────────────────────────────────────────────────────

class OptimizationRun(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    scenario_id: str = Field(foreign_key="scenario.id")
    solver_used: str = "pulp_cbc"
    status: str = "pending"  # pending | running | done | error | infeasible
    objective_value: Optional[float] = None
    total_cost_inr: Optional[float] = None
    total_import_kwh: Optional[float] = None
    total_export_kwh: Optional[float] = None
    total_curtailed_kwh: Optional[float] = None
    total_unmet_kwh: Optional[float] = None
    renewable_utilization_pct: Optional[float] = None
    schedule_json: Optional[str] = None  # JSON array of interval schedules
    summary_json: Optional[str] = None
    warnings: Optional[str] = None  # JSON
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    scenario: Optional[Scenario] = Relationship(back_populates="optimization_runs")


class BaselineRun(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    scenario_id: str = Field(foreign_key="scenario.id")
    strategy: str = "simple_priority"
    status: str = "pending"
    total_cost_inr: Optional[float] = None
    total_import_kwh: Optional[float] = None
    total_export_kwh: Optional[float] = None
    total_curtailed_kwh: Optional[float] = None
    total_unmet_kwh: Optional[float] = None
    renewable_utilization_pct: Optional[float] = None
    schedule_json: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    scenario: Optional[Scenario] = Relationship(back_populates="baseline_runs")


class ComparisonResult(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True)
    optimization_run_id: str = Field(foreign_key="optimizationrun.id")
    baseline_run_id: str = Field(foreign_key="baselinerun.id")
    cost_saving_inr: Optional[float] = None
    cost_saving_pct: Optional[float] = None
    import_reduction_kwh: Optional[float] = None
    curtailment_change_kwh: Optional[float] = None
    renewable_util_improvement_pct: Optional[float] = None
    comparison_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
