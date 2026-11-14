from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(database_url: str) -> list[str]:
    """Bring the schema up to date. Returns the revisions applied, oldest first."""
    config = _config(database_url)
    before = _current(database_url)
    command.upgrade(config, "head")
    script = ScriptDirectory.from_config(config)
    applied = [
        revision.revision
        for revision in script.iterate_revisions("head", before)
        if revision.revision != before
    ]
    return list(reversed(applied))


def write_revision(database_url: str, message: str) -> None:
    """Write a new migration by comparing the tables in code with the database, which must
    be up to date. Read the generated file before committing it; autogenerate does not see
    every kind of change."""
    command.revision(_config(database_url), message=message, autogenerate=True)


def _config(database_url: str) -> Config:
    # Configured in code, so the installed package can migrate without an alembic.ini.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # Alembic treats % as interpolation syntax.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _current(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
