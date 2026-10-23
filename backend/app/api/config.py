"""Site and Asset configuration API endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from datetime import datetime

from app.core.database import get_session
from app.models.db_models import SiteConfig
from app.models.schemas import (
    SiteConfigResponse, SiteConfigUpdate,
    BatteryConfig, GridConfig, TariffConfig, EVConfig
)

router = APIRouter()


def _get_or_create_site(session: Session) -> SiteConfig:
    site = session.exec(select(SiteConfig)).first()
    if not site:
        site = SiteConfig()
        session.add(site)
        session.commit()
        session.refresh(site)
    return site


@router.get("", response_model=SiteConfigResponse)
async def get_site_config(session: Session = Depends(get_session)):
    """Retrieve current site and asset configuration."""
    site = _get_or_create_site(session)
    return SiteConfigResponse(
        id=site.id,
        name=site.name,
        timezone=site.timezone,
        currency=site.currency,
        solar_capacity_kw=site.solar_capacity_kw,
        wind_capacity_kw=site.wind_capacity_kw,
        has_wind=site.has_wind,
        battery=BatteryConfig(
            capacity_kwh=site.battery_capacity_kwh,
            min_soc_pct=site.battery_min_soc_pct,
            max_soc_pct=site.battery_max_soc_pct,
            initial_soc_pct=site.battery_initial_soc_pct,
            charge_power_kw=site.battery_charge_power_kw,
            discharge_power_kw=site.battery_discharge_power_kw,
            charge_efficiency=site.battery_charge_efficiency,
            discharge_efficiency=site.battery_discharge_efficiency,
            reserve_pct=site.battery_reserve_pct,
        ),
        tariff=TariffConfig(
            import_tariff_inr_kwh=site.import_tariff_inr_kwh,
            export_tariff_inr_kwh=site.export_tariff_inr_kwh,
            export_permitted=site.export_permitted,
        ),
        grid=GridConfig(
            import_limit_kw=site.grid_import_limit_kw,
            export_limit_kw=site.grid_export_limit_kw,
            export_permitted=site.export_permitted,
        ),
        ev=EVConfig(
            enabled=site.ev_charger_enabled,
            charger_power_kw=site.ev_charger_power_kw,
            daily_demand_kwh=site.ev_daily_demand_kwh,
            window_start_hour=18,
            window_end_hour=22,
        ),
        forecast_horizon_hours=site.forecast_horizon_hours,
        interval_hours=site.interval_hours,
    )


@router.put("", response_model=SiteConfigResponse)
async def update_site_config(body: SiteConfigUpdate, session: Session = Depends(get_session)):
    """Update site and asset parameters."""
    site = _get_or_create_site(session)

    if body.name is not None:
        site.name = body.name
    if body.timezone is not None:
        site.timezone = body.timezone
    if body.currency is not None:
        site.currency = body.currency
    if body.solar_capacity_kw is not None:
        site.solar_capacity_kw = body.solar_capacity_kw
    if body.wind_capacity_kw is not None:
        site.wind_capacity_kw = body.wind_capacity_kw
    if body.has_wind is not None:
        site.has_wind = body.has_wind

    if body.battery is not None:
        site.battery_capacity_kwh = body.battery.capacity_kwh
        site.battery_min_soc_pct = body.battery.min_soc_pct
        site.battery_max_soc_pct = body.battery.max_soc_pct
        site.battery_initial_soc_pct = body.battery.initial_soc_pct
        site.battery_charge_power_kw = body.battery.charge_power_kw
        site.battery_discharge_power_kw = body.battery.discharge_power_kw
        site.battery_charge_efficiency = body.battery.charge_efficiency
        site.battery_discharge_efficiency = body.battery.discharge_efficiency
        site.battery_reserve_pct = body.battery.reserve_pct

    if body.tariff is not None:
        site.import_tariff_inr_kwh = body.tariff.import_tariff_inr_kwh
        site.export_tariff_inr_kwh = body.tariff.export_tariff_inr_kwh
        site.export_permitted = body.tariff.export_permitted

    if body.grid is not None:
        site.grid_import_limit_kw = body.grid.import_limit_kw
        site.grid_export_limit_kw = body.grid.export_limit_kw
        site.export_permitted = body.grid.export_permitted

    if body.ev is not None:
        site.ev_charger_enabled = body.ev.enabled
        site.ev_charger_power_kw = body.ev.charger_power_kw
        site.ev_daily_demand_kwh = body.ev.daily_demand_kwh

    if body.forecast_horizon_hours is not None:
        site.forecast_horizon_hours = body.forecast_horizon_hours
    if body.interval_hours is not None:
        site.interval_hours = body.interval_hours

    site.updated_at = datetime.utcnow()
    session.add(site)
    session.commit()
    session.refresh(site)

    return await get_site_config(session)
