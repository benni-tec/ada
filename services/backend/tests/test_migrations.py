from alembic import command
from sqlalchemy import create_engine, inspect

from ada.adapters.db.base import Base
from ada.adapters.db.migrate import _config, migrate


def test_migrations_build_every_table_from_an_empty_database(database_url: str) -> None:
    applied = migrate(database_url)

    assert applied == ["0001", "0002"]
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert tables == set(Base.metadata.tables) | {"alembic_version"}


def test_migrating_twice_applies_nothing_the_second_time(database_url: str) -> None:
    migrate(database_url)
    assert migrate(database_url) == []


def test_the_tables_in_code_match_the_migrations(migrated_database_url: str) -> None:
    # Fails when a table was changed without writing a migration for it.
    command.check(_config(migrated_database_url))


def test_every_migration_can_be_undone(database_url: str) -> None:
    migrate(database_url)
    command.downgrade(_config(database_url), "0001")
    engine = create_engine(database_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("alerts")}
    finally:
        engine.dispose()
    assert "condition_operator_id" not in columns
    assert migrate(database_url) == ["0002"]
