import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

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
