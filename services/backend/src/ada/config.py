from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/widgets/dist of this checkout, for a backend running from source.
SOURCE_WIDGETS_DIR = Path(__file__).resolve().parents[3] / "widgets" / "dist"


class Settings(BaseSettings):
    """Read from the environment. The URLs are required so a misconfigured container
    stops at startup; moon sets the development values (services/backend/moon.yml)."""

    # populate_by_name: callers pass secret_key by its name, the environment by its alias.
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

    # The master key that encrypts the model providers' API keys in the database: a Fernet
    # key, or several separated by commas (the first encrypts, all decrypt, for rotation).
    # Or the file holding it (Docker secrets). Neither set: the platform runs, but no API
    # key can be stored.
    secret_key: SecretStr | None = Field(None, validation_alias="ADA_SECRET_KEY")
    secret_key_file: Path | None = Field(None, validation_alias="ADA_SECRET_KEY_FILE")

    # Web tools, from the environment only. A tool without its setting fails with a message
    # naming it; nothing else is affected.
    exa_api_key: SecretStr | None = None
    context_api_key: SecretStr | None = None
    # Where Context.dev can reach this platform, for page monitor webhooks.
    ada_public_url: str | None = None

    def master_key(self) -> str | None:
        """ADA_SECRET_KEY, else the contents of ADA_SECRET_KEY_FILE; None when neither is
        set. A file that is named but cannot be read is an error, not a missing key."""
        if self.secret_key is not None and self.secret_key.get_secret_value().strip():
            return self.secret_key.get_secret_value().strip()
        if self.secret_key_file is not None:
            return self.secret_key_file.read_text().strip() or None
        return None
