"""Health check endpoints."""
from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.core.config import settings

router = APIRouter()


@router.get("", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        message="EnerShare AI backend is running",
    )


@router.get("/detailed")
async def detailed_health():
    import xgboost
    import pulp
    xgb_version = xgboost.__version__
    pulp_version = pulp.__version__

    return {
        "status": "ok",
        "version": settings.app_version,
        "components": {
            "fastapi": "online",
            "xgboost": f"available ({xgb_version})",
            "pulp_optimizer": f"available ({pulp_version})",
            "database": "sqlite",
        },
        "data_mode": "demo",
    }
