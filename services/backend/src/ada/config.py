from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment. The URLs are required so a misconfigured container
    stops at startup; moon sets the development values (services/backend/moon.yml)."""

    model_config = SettingsConfigDict(extra="ignore")

    # Definitions: projects, operators, runs, dashboards. SQLAlchemy URL for psycopg 3.
    database_url: str = Field(min_length=1)
    db_pool_size: int = 10

    # Task queue broker and event channel; Valkey speaks the Redis protocol.
    valkey_url: str = Field(min_length=1)

    # Analysis data: one Parquet file per snapshot, shared by the API and the workers.
    data_dir: Path = Path("data")
