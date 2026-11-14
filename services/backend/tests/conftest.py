import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from ada.adapters.db.base import Base
from ada.adapters.db.migrate import migrate
from ada.config import Settings

# The development database of docker-compose.infra.yml; moon sets the same value.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ada:ada-dev@localhost:5434/ada")
# Never the developer's master key (moon run :dev keeps one in .env.local): tests that store
# API keys bring their own.
os.environ.pop("ADA_SECRET_KEY", None)
os.environ.pop("ADA_SECRET_KEY_FILE", None)
# Nor the developer's Context.dev key: no test calls it.
os.environ.pop("CONTEXT_DEV_API_KEY", None)
os.environ.pop("CONTEXT_API_KEY", None)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    # Session-wide, so an app or MCP client can be shared by the tests of a module.
    return "asyncio"


def settings_in(
    data_dir: Path, database_url: str = "postgresql+psycopg://test@127.0.0.1:1/test"
) -> Settings:
    """Settings for a test. Nothing listens on port 1, so the database (unless one is
    given) and Valkey are unreachable."""
    return Settings(
        database_url=database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=data_dir
    )


@pytest.fixture(scope="session")
def unreachable_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return settings_in(tmp_path_factory.mktemp("data"))


# The analysis store needs no server, so it works even when everything else is down.
UNREACHABLE_HEALTH = {
    "status": "degraded",
    "api": "ok",
    "database": "unavailable",
    "queue": "unavailable",
    "worker": "unavailable",
    "analysis_store": "ok",
}


@pytest.fixture(scope="session")
def postgres() -> Iterator[psycopg.Connection]:
    """A connection to the PostgreSQL at DATABASE_URL that creates and drops databases.

    Skipped when PostgreSQL is not running (start it with `moon run root:infra`), except
    in CI, which always provides it.
    """
    url = make_url(os.environ["DATABASE_URL"])
    try:
        admin = psycopg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            dbname=url.database,
            autocommit=True,
            connect_timeout=2,
        )
    except psycopg.OperationalError as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    with admin:
        yield admin


def _create_database(admin: psycopg.Connection) -> tuple[str, str]:
    name = f"test_{uuid.uuid4().hex}"
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_url(os.environ["DATABASE_URL"]).set(database=name)
    return name, url.render_as_string(hide_password=False)


def _drop_database(admin: psycopg.Connection, name: str) -> None:
    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def database_url(postgres: psycopg.Connection) -> Iterator[str]:
    """A new, empty database, dropped afterwards: for the tests of the migrations."""
    name, url = _create_database(postgres)
    try:
        yield url
    finally:
        _drop_database(postgres, name)


@pytest.fixture(scope="session")
def _migrated(postgres: psycopg.Connection) -> Iterator[tuple[str, psycopg.Connection]]:
    name, url = _create_database(postgres)
    migrate(url)
    conninfo = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            yield url, connection
    finally:
        _drop_database(postgres, name)


@pytest.fixture
def migrated_database_url(_migrated: tuple[str, psycopg.Connection]) -> str:
    """The one database with the current schema, migrated once per run and emptied before
    each test: much faster than a database of its own per test."""
    url, connection = _migrated
    tables = sql.SQL(", ").join(sql.Identifier(name) for name in Base.metadata.tables)
    # A test that left a connection open would make this wait; fail instead.
    connection.execute("SET lock_timeout = '5s'")
    connection.execute(sql.SQL("TRUNCATE {} CASCADE").format(tables))
    # What the migrations seed: the one row of the agent settings (0005).
    connection.execute(
        "INSERT INTO agent_settings (id, session_agent_model_id, revision) VALUES (1, NULL, 1)"
    )
    return url
