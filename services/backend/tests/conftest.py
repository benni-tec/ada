from pathlib import Path

import pytest

from ada.config import Settings


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
