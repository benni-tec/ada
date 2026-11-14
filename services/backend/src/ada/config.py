from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
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
    # Context.dev's API key, for document sources with `options.engine: "context.dev"`,
    # web sources, page monitors and the web tools (read_page, extract_table, map_site), all
    # on ADA's account.
    context_dev_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("CONTEXT_DEV_API_KEY", "CONTEXT_API_KEY")
    )
    # Exa's API key, for search_web. Unset: the tool refuses, naming it.
    exa_api_key: SecretStr | None = None
    # Web credits each project may spend per day (UTC): the web tools (Exa searches
    # included, see WEB_SEARCH_CREDITS) and web sources together.
    web_daily_credit_limit: int = Field(300, ge=0)
    # Where Context.dev can reach this platform, for page monitor webhooks. Unset:
    # watching refuses, naming it.
    ada_public_url: str | None = None
    # Paid web tool calls (Exa and Context.dev) a research session may make.
    research_web_calls: int = 40

    # URL, request and downloaded document sources read public addresses only; true lets
    # them read loopback and private ones too, for local development and tests. Never in
    # production: addresses come from the web through the research agent.
    allow_private_sources: bool = False
    # The most a URL, request or document source may answer, in bytes once decoded.
    source_max_bytes: int = Field(50_000_000, gt=0)

    def master_key(self) -> str | None:
        """ADA_SECRET_KEY, else the contents of ADA_SECRET_KEY_FILE; None when neither is
        set. A file that is named but cannot be read is an error, not a missing key."""
        if self.secret_key is not None and self.secret_key.get_secret_value().strip():
            return self.secret_key.get_secret_value().strip()
        if self.secret_key_file is not None:
            return self.secret_key_file.read_text().strip() or None
        return None
