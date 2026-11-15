import asyncio
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import Uuid, select, text, union_all
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ada.adapters.db.tables import Base
from ada.core.ports.system import Database


class EngineDatabase(Database):
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def is_reachable(self) -> bool:
        try:
            async with asyncio.timeout(2):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except SQLAlchemyError, OSError, TimeoutError:
            return False
        return True


class EngineProjectOwners:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.tables = [
            table
            for table in Base.metadata.sorted_tables
            if "id" in table.c
            and isinstance(table.c.id.type, Uuid)
            and (table.name == "projects" or "project_id" in table.c)
        ]

    async def of(self, ids: Collection[UUID]) -> set[UUID]:
        owners = union_all(
            *(
                select(table.c.id if table.name == "projects" else table.c.project_id).where(
                    table.c.id.in_(ids)
                )
                for table in self.tables
            )
        )
        async with self.engine.connect() as connection:
            return set((await connection.scalars(owners)).all())
