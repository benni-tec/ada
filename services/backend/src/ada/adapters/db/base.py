from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base of every table. Alembic compares its metadata with the database to write
    migrations, so each table module must be imported in migrations/env.py."""
