from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ada.adapters.db.tables import WebUsageRow
from ada.core.models.base import Id
from ada.core.ports.web import WebBudget


class SqlWebBudget(WebBudget):
    """Counts credits in `web_usage`, each write a short transaction on a connection of
    its own, like SqlSourceCheckLog: a refused or failed call stays counted when the
    caller's unit of work rolls back. One upsert checks and counts at once, so two calls
    at the same time cannot both take the last credits."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def spend(self, project_id: Id, day: date, credits: int, limit: int) -> bool:
        if credits > limit:
            return False
        table = WebUsageRow.__table__
        statement = insert(table).values(project_id=project_id, day=day, credits=credits)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.project_id, table.c.day],
            set_={"credits": table.c.credits + statement.excluded.credits},
            where=table.c.credits + statement.excluded.credits <= limit,
        ).returning(table.c.credits)
        async with AsyncSession(self.engine) as session, session.begin():
            counted = (await session.execute(statement)).scalar_one_or_none()
        return counted is not None

    async def adjust(self, project_id: Id, day: date, credits: int) -> None:
        table = WebUsageRow.__table__
        statement = insert(table).values(project_id=project_id, day=day, credits=max(credits, 0))
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.project_id, table.c.day],
            set_={"credits": func.greatest(table.c.credits + credits, 0)},
        )
        async with AsyncSession(self.engine) as session, session.begin():
            await session.execute(statement)
