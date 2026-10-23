"""
Main API router — aggregates all sub-routers.
"""
from fastapi import APIRouter
from app.api import health, datasets, scenarios, forecast, optimize, reports, config

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(scenarios.router, prefix="/scenarios", tags=["scenarios"])
api_router.include_router(forecast.router, prefix="/forecast", tags=["forecast"])
api_router.include_router(optimize.router, prefix="/optimize", tags=["optimize"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(config.router, prefix="/config", tags=["config"])
