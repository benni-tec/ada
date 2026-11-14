from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/widgets/dist of this checkout, for a backend running from source.
SOURCE_WIDGETS_DIR = Path(__file__).resolve().parents[3] / "widgets" / "dist"


class Settings(BaseSettings):
    """Read from the environment. The URLs are required so a misconfigured container
    stops at startup; moon sets the development values (services/backend/moon.yml)."""

    # populate_by_name: callers pass llms_config by its name, the environment by its alias.
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # Definitions: projects, operators, runs, dashboards. SQLAlchemy URL for psycopg 3.
    database_url: str = Field(min_length=1)
    db_pool_size: int = 10

    # Task queue broker and event channel; Valkey speaks the Redis protocol.
    valkey_url: str = Field(min_length=1)

    # Analysis data: one Parquet file per snapshot, shared by the API and the workers.
    data_dir: Path = Path("data")

    # The built widgets (services/widgets, `moon run widgets:build`), one <type>.html each,
    # served to the frontend and as MCP App resources. The image sets its own copy.
    widgets_dir: Path = SOURCE_WIDGETS_DIR

    # The models file of the in-platform agent (llms.example.yml shows the format). A
    # missing file means no agent, not an error.
    llms_config: Path = Field(Path("llms.yml"), validation_alias="ADA_LLMS_CONFIG")
