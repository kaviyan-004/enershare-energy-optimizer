"""Pydantic request/response schemas for API validation."""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
import uuid


# ─── Generic ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ─── Site Config ──────────────────────────────────────────────────────────────

class BatteryConfig(BaseModel):
    capacity_kwh: float = Field(100.0, ge=0.1, le=10000.0)
    min_soc_pct: float = Field(20.0, ge=0.0, le=100.0)
    max_soc_pct: float = Field(95.0, ge=0.0, le=100.0)
    initial_soc_pct: float = Field(50.0, ge=0.0, le=100.0)
    charge_power_kw: float = Field(25.0, ge=0.0)
    discharge_power_kw: float = Field(25.0, ge=0.0)
    charge_efficiency: float = Field(0.95, ge=0.5, le=1.0)
    discharge_efficiency: float = Field(0.95, ge=0.5, le=1.0)
    reserve_pct: float = Field(20.0, ge=0.0, le=100.0)

    @model_validator(mode='after')
    def validate_soc_range(self):
        if self.min_soc_pct >= self.max_soc_pct:
            raise ValueError("min_soc_pct must be less than max_soc_pct")
        if not (self.min_soc_pct <= self.initial_soc_pct <= self.max_soc_pct):
            raise ValueError("initial_soc_pct must be between min and max")
        return self


class TariffConfig(BaseModel):
    import_tariff_inr_kwh: float = Field(8.5, ge=0.0)
    export_tariff_inr_kwh: float = Field(3.0, ge=0.0)
    export_permitted: bool = False


class GridConfig(BaseModel):
    import_limit_kw: float = Field(100.0, ge=0.0)
    export_limit_kw: float = Field(50.0, ge=0.0)
    export_permitted: bool = False


class EVConfig(BaseModel):
    enabled: bool = False
    charger_power_kw: float = Field(7.4, ge=0.0)
    daily_demand_kwh: float = Field(30.0, ge=0.0)
    window_start_hour: int = Field(18, ge=0, le=23)
    window_end_hour: int = Field(22, ge=0, le=23)


class SiteConfigResponse(BaseModel):
    id: str
    name: str
    timezone: str
    currency: str
    solar_capacity_kw: float
    wind_capacity_kw: float
    has_wind: bool
    battery: BatteryConfig
    tariff: TariffConfig
    grid: GridConfig
    ev: EVConfig
    forecast_horizon_hours: int
    interval_hours: float


class SiteConfigUpdate(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    solar_capacity_kw: Optional[float] = None
    wind_capacity_kw: Optional[float] = None
    has_wind: Optional[bool] = None
    battery: Optional[BatteryConfig] = None
    tariff: Optional[TariffConfig] = None
    grid: Optional[GridConfig] = None
    ev: Optional[EVConfig] = None
    forecast_horizon_hours: Optional[int] = None
    interval_hours: Optional[float] = None


# ─── Dataset ──────────────────────────────────────────────────────────────────

class DatasetSummary(BaseModel):
    id: str
    name: str
    source: str
    row_count: int
    start_timestamp: Optional[datetime]
    end_timestamp: Optional[datetime]
    interval_hours: float
    has_solar: bool
    has_wind: bool
    quality_warnings: Optional[List[str]]
    created_at: datetime


class DatasetValidationResult(BaseModel):
    valid: bool
    row_count: int
    warnings: List[str]
    errors: List[str]
    columns_found: List[str]
    missing_required_columns: List[str]
    duplicate_timestamps: int
    missing_values: Dict[str, int]
    preview: List[Dict[str, Any]]


# ─── Energy Time-Series Record ────────────────────────────────────────────────

class EnergyRecord(BaseModel):
    timestamp: datetime
    solar_kwh: float = 0.0
    wind_kwh: float = 0.0
    demand_kwh: float = 0.0
    irradiance_wm2: Optional[float] = None
    temperature_c: Optional[float] = None
    cloud_cover_pct: Optional[float] = None
    wind_speed_ms: Optional[float] = None
    battery_soc_pct: Optional[float] = None
    grid_import_kwh: Optional[float] = None
    grid_export_kwh: Optional[float] = None
    import_tariff_inr_kwh: Optional[float] = None
    data_quality: str = "measured"  # measured | estimated | simulated | forecast


# ─── Scenario ─────────────────────────────────────────────────────────────────

class ScenarioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    preset: Optional[str] = None
    dataset_id: Optional[str] = None
    battery: Optional[BatteryConfig] = None
    tariff: Optional[TariffConfig] = None
    grid: Optional[GridConfig] = None
    ev: Optional[EVConfig] = None
    solar_scale_factor: float = 1.0
    demand_scale_factor: float = 1.0
    horizon_hours: int = 24


class ScenarioResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    preset: Optional[str]
    dataset_id: Optional[str]
    created_at: datetime
    updated_at: datetime


# ─── Forecast ─────────────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    dataset_id: str
    target: str  # "generation" | "demand"
    model_name: str = "xgboost"  # "persistence" | "gradient_boost" | "xgboost"
    horizon_hours: int = 24
    include_baseline_comparison: bool = True


class ForecastPoint(BaseModel):
    timestamp: datetime
    actual: Optional[float] = None
    predicted: float
    source: str = "forecast"  # actual | forecast | demo


class ForecastResponse(BaseModel):
    run_id: str
    target: str
    model_name: str
    horizon_hours: int
    mae: Optional[float]
    rmse: Optional[float]
    mape: Optional[float]
    baseline_mae: Optional[float]
    baseline_rmse: Optional[float]
    points: List[ForecastPoint]
    warnings: List[str]
    feature_list: List[str]
    status: str


# ─── Optimization ─────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    scenario_id: str
    use_forecast: bool = True
    generation_kwh: Optional[List[float]] = None  # override with explicit values
    demand_kwh: Optional[List[float]] = None


class IntervalSchedule(BaseModel):
    interval: int
    timestamp: datetime
    renewable_gen_kwh: float
    demand_kwh: float
    renewable_used_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    battery_soc_pct: float
    grid_import_kwh: float
    grid_export_kwh: float
    curtailed_kwh: float
    ev_served_kwh: float
    unmet_demand_kwh: float
    interval_cost_inr: float
    action_summary: str
    constraint_notes: List[str]


class OptimizationResponse(BaseModel):
    run_id: str
    status: str
    solver: str
    objective_value: Optional[float]
    total_cost_inr: Optional[float]
    total_import_kwh: Optional[float]
    total_export_kwh: Optional[float]
    total_curtailed_kwh: Optional[float]
    total_unmet_kwh: Optional[float]
    renewable_utilization_pct: Optional[float]
    schedule: List[IntervalSchedule]
    recommendation: str
    warnings: List[str]
    error_message: Optional[str]


class BaselineResponse(BaseModel):
    run_id: str
    strategy: str
    total_cost_inr: float
    total_import_kwh: float
    total_export_kwh: float
    total_curtailed_kwh: float
    total_unmet_kwh: float
    renewable_utilization_pct: float
    schedule: List[IntervalSchedule]


class ComparisonResponse(BaseModel):
    scenario_id: str
    optimization_run_id: str
    baseline_run_id: str
    optimized: Dict[str, Any]
    baseline: Dict[str, Any]
    savings: Dict[str, Any]
    comparison_table: List[Dict[str, Any]]


# ─── KPI Dashboard ────────────────────────────────────────────────────────────

class KPISummary(BaseModel):
    site_name: str
    data_mode: str
    last_calculation: Optional[datetime]
    forecast_model_status: str
    optimization_status: str
    renewable_generation_kwh: float
    energy_demand_kwh: float
    battery_soc_pct: float
    surplus_or_deficit_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    renewable_utilization_pct: float
    estimated_cost_inr: float
    forecast_mae: Optional[float]
    recommendation: str
    is_simulated: bool
