"""Database setup with SQLAlchemy and SQLModel."""
from sqlmodel import SQLModel, create_engine, Session
from app.core.config import settings
import os

# Ensure data directory exists
os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.uploads_dir, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
