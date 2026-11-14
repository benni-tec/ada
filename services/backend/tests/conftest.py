import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from ada.adapters.db.migrate import migrate
from ada.config import Settings

# The development database of docker-compose.infra.yml; moon sets the same value.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ada:ada-dev@localhost:5434/ada")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def unreachable_settings(tmp_path: Path) -> Settings:
    # Nothing listens on port 1, so the database and Valkey are always unreachable here.
    return Settings(
        database_url="postgresql+psycopg://test@127.0.0.1:1/test",
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )


# The analysis store needs no server, so it works even when everything else is down.
UNREACHABLE_HEALTH = {
    "status": "degraded",
    "api": "ok",
    "database": "unavailable",
    "queue": "unavailable",
    "worker": "unavailable",
    "analysis_store": "ok",
}


@pytest.fixture
def database_url() -> Iterator[str]:
    """A new, empty database on the PostgreSQL at DATABASE_URL, dropped afterwards.

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
    name = f"test_{uuid.uuid4().hex}"
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield url.set(database=name).render_as_string(hide_password=False)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def migrated_database_url(database_url: str) -> str:
    """A database with the current schema, for tests of the database repositories."""
    migrate(database_url)
    return database_url
