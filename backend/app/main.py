"""EnerShare AI — Main FastAPI Application Entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
from sqlmodel import Session, select
import os

from app.core.config import settings
from app.core.database import create_db_and_tables, engine
from app.api.router import api_router
from app.models.db_models import Dataset, SiteConfig, Scenario
from app.services.demo_data import generate_demo_dataset


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # 1. Initialize DB tables
    create_db_and_tables()

    # 2. Seed initial demo data and site config
    with Session(engine) as session:
        # Site Config
        site = session.exec(select(SiteConfig)).first()
        if not site:
            site = SiteConfig(
                name="Demo Commercial Precision Facility",
                timezone="Asia/Kolkata",
                currency="INR",
                solar_capacity_kw=50.0,
                wind_capacity_kw=0.0,
                has_wind=False,
                battery_capacity_kwh=100.0,
                battery_min_soc_pct=20.0,
                battery_max_soc_pct=95.0,
                battery_initial_soc_pct=50.0,
                battery_charge_power_kw=25.0,
                battery_discharge_power_kw=25.0,
                grid_import_limit_kw=100.0,
                grid_export_limit_kw=50.0,
                export_permitted=False,
                import_tariff_inr_kwh=8.5,
                export_tariff_inr_kwh=3.0,
                ev_charger_enabled=True,
                ev_charger_power_kw=7.4,
                ev_daily_demand_kwh=30.0,
            )
            session.add(site)
            session.commit()

        # Seed Demo Dataset
        demo_ds = session.exec(select(Dataset).where(Dataset.source == "demo")).first()
        if not demo_ds:
            df = generate_demo_dataset(days=30)
            demo_ds = Dataset(
                name="Demo 30-Day Solar & Demand Profile",
                source="demo",
                row_count=len(df),
                start_timestamp=df["timestamp"].iloc[0].to_pydatetime(),
                end_timestamp=df["timestamp"].iloc[-1].to_pydatetime(),
                interval_hours=1.0,
                has_solar=True,
                has_wind=False,
                has_weather=True,
            )
            session.add(demo_ds)
            session.commit()
            session.refresh(demo_ds)

        # Seed Default Presets if none exist
        existing_scenario = session.exec(select(Scenario)).first()
        if not existing_scenario:
            presets = [
                ("Base 24h Factory Schedule", "Default normal operational conditions with factory load and rooftop solar.", "base"),
                ("Solar Surplus Scenario", "Midday high generation exceeding demand; tests storage & curtailment.", "solar_surplus"),
                ("Energy Deficit Scenario", "Heavy machinery run under poor solar generation; tests battery discharge & grid import.", "deficit"),
                ("High Peak Tariff Window", "Simulates TOD evening tariff penalty; tests storage arbitrage.", "high_tariff"),
                ("Zero-Export Grid Restriction", "Grid export strictly prohibited by utility; tests surplus absorption.", "export_disabled"),
            ]
            for sname, sdesc, spreset in presets:
                sc = Scenario(
                    name=sname,
                    description=sdesc,
                    preset=spreset,
                    dataset_id=demo_ds.id if demo_ds else None,
                )
                session.add(sc)
            session.commit()

    yield


app = FastAPI(
    title="EnerShare AI API",
    description=(
        "Intelligent Renewable Energy Exchange and Smart Storage Optimization Platform."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix="/api")

# Serve frontend build if present
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
else:
    frontend_static = Path(__file__).parent.parent.parent / "frontend"
    if (frontend_static / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend_static), html=True), name="static")
