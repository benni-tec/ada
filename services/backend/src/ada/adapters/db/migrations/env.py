"""Alembic environment. Run through `ada migrate`; new revisions are written with
`moon run backend:revision -- "<message>"` (`ada revision`)."""

from alembic import context
from sqlalchemy import create_engine

from ada.adapters.db.base import Base

# Import every module that defines tables here, so autogenerate sees them.

target_metadata = Base.metadata


def run_migrations() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    assert url, "sqlalchemy.url is set by ada.adapters.db.migrate"
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
