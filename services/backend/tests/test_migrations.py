from alembic import command
from sqlalchemy import create_engine, inspect

from ada.adapters.db.base import Base
from ada.adapters.db.migrate import _config, migrate


def test_migrations_build_every_table_from_an_empty_database(database_url: str) -> None:
    applied = migrate(database_url)

    assert applied == ["0001", "0002", "0003"]
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
    assert migrate(database_url) == ["0002", "0003"]


def test_0003_adds_turns_context_and_copies_and_takes_them_back(database_url: str) -> None:
    migrate(database_url)
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "agent_turns" in inspector.get_table_names()
        entry_columns = {c["name"]: c for c in inspector.get_columns("session_entries")}
        assert "'[]'::jsonb" in str(entry_columns["context"]["default"])
        widget_keys = inspector.get_foreign_keys("widgets")
        assert any(key["constrained_columns"] == ["copied_from"] for key in widget_keys)

        command.downgrade(config, "0002")

        inspector = inspect(engine)
        assert "agent_turns" not in inspector.get_table_names()
        assert "context" not in {c["name"] for c in inspector.get_columns("session_entries")}
        assert "copied_from" not in {c["name"] for c in inspector.get_columns("widgets")}
    finally:
        engine.dispose()
    assert migrate(database_url) == ["0003"]
