"""Application configuration using pydantic-settings."""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "EnerShare AI"
    app_version: str = "1.0.0-prototype"
    debug: bool = True

    # Database
    database_url: str = "sqlite:///./enershare.db"

    # Paths
    base_dir: Path = Path(__file__).parent.parent.parent
    data_dir: Path = Path(__file__).parent.parent.parent / "data"
    uploads_dir: Path = Path(__file__).parent.parent.parent / "data" / "uploads"

    # Upload limits
    max_upload_size_mb: int = 10

    # Demo site defaults
    demo_site_name: str = "Demo Commercial Facility"
    demo_solar_capacity_kw: float = 50.0
    demo_battery_capacity_kwh: float = 100.0

    # Optimization defaults
    default_interval_hours: float = 1.0
    default_horizon_hours: int = 24

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
