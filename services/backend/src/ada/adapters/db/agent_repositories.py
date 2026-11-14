"""The in-platform agent's turns."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ada.adapters.db.support import add_row, dump_all, fetch, oldest_first, require, rows
from ada.adapters.db.tables import AgentTurnRow, SessionEntryRow
from ada.core.models.agents import AgentTurn, TurnPart, TurnStatus
from ada.core.models.base import Id
from ada.core.models.errors import NotFound
from ada.core.ports.agents import TurnProgress
from ada.core.ports.repositories import AgentTurnRepository


def _turn(row: AgentTurnRow) -> AgentTurn:
    return AgentTurn(
        id=row.id,
        session_id=row.session_id,
        prompt_entry_id=row.prompt_entry_id,
        model=row.model,
        status=TurnStatus(row.status),
        parts=row.parts,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


UNFINISHED = (TurnStatus.QUEUED.value, TurnStatus.RUNNING.value)


class SqlAgentTurnRepository(AgentTurnRepository):
    """Every write after `add` is a plain UPDATE of the columns it means, so the worker's
    progress and a cancel request never overwrite each other. The worker's writes are
    conditional on the turn still running, so a turn failed elsewhere stays failed."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> AgentTurn:
        return _turn(await fetch(self.session, AgentTurnRow, id, "agent turn"))

    async def add(self, turn: AgentTurn) -> None:
        # The message it answers belongs to its session, so this also checks the session.
        await require(self.session, SessionEntryRow, turn.prompt_entry_id, "session entry")
        row = AgentTurnRow(
            id=turn.id,
            session_id=turn.session_id,
            prompt_entry_id=turn.prompt_entry_id,
            model=turn.model,
            status=turn.status.value,
            parts=dump_all(turn.parts),
            error=turn.error,
            cancel_requested=False,
            settled=False,
            created_at=turn.created_at,
            finished_at=turn.finished_at,
        )
        await add_row(self.session, row)

    async def list(self, session_id: Id) -> Sequence[AgentTurn]:
        statement = oldest_first(AgentTurnRow, AgentTurnRow.session_id == session_id)
        return [_turn(row) for row in await rows(self.session, statement)]

    async def start(self, id: Id, at: datetime) -> bool:
        changed = await self._update(
            id,
            AgentTurnRow.status == TurnStatus.QUEUED.value,
            status=TurnStatus.RUNNING.value,
            started_at=at,
        )
        if not changed:
            await self.get(id)
        return changed

    async def save_parts(self, id: Id, parts: Sequence[TurnPart]) -> bool:
        return await self._running_update(id, parts=dump_all(parts))

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn | None:
        changed = await self._running_update(
            id, status=status.value, parts=dump_all(parts), error=error, finished_at=at
        )
        return await self.get(id) if changed else None

    async def settle(self, id: Id) -> bool:
        ended = AgentTurnRow.status.not_in(UNFINISHED)
        if await self._update(id, ended, AgentTurnRow.settled.is_(False), settled=True):
            return True
        await self.get(id)
        return False

    async def unsettled(
        self, started_before: datetime, finished_before: datetime
    ) -> Sequence[AgentTurn]:
        overdue = and_(
            AgentTurnRow.status == TurnStatus.RUNNING.value,
            AgentTurnRow.started_at < started_before,
        )
        ended = and_(
            AgentTurnRow.status.not_in(UNFINISHED), AgentTurnRow.finished_at < finished_before
        )
        statement = oldest_first(AgentTurnRow, ~AgentTurnRow.settled, or_(overdue, ended))
        return [_turn(row) for row in await rows(self.session, statement)]

    async def abandon(self, id: Id, error: str, at: datetime) -> bool:
        """TurnProgress.abandon; False when the turn has ended already."""
        return await self._update(
            id,
            AgentTurnRow.status.in_(UNFINISHED),
            status=TurnStatus.FAILED.value,
            error=error,
            finished_at=at,
            cancel_requested=True,
        )

    async def request_cancel(self, id: Id, at: datetime) -> AgentTurn:
        # One statement each, so a worker starting the turn at the same moment either
        # finds it cancelled or has started it and sees the flag at its next step.
        cancelled = await self._update(
            id,
            AgentTurnRow.status == TurnStatus.QUEUED.value,
            status=TurnStatus.CANCELLED.value,
            finished_at=at,
            cancel_requested=True,
        )
        if not cancelled:
            await self._update(
                id, AgentTurnRow.status == TurnStatus.RUNNING.value, cancel_requested=True
            )
        return await self.get(id)

    async def cancel_requested(self, id: Id) -> bool:
        flag = await self.session.scalar(
            select(AgentTurnRow.cancel_requested).where(AgentTurnRow.id == id)
        )
        if flag is None:
            raise NotFound("agent turn", id)
        return flag

    async def _running_update(self, id: Id, **values: object) -> bool:
        if await self._update(id, AgentTurnRow.status == TurnStatus.RUNNING.value, **values):
            return True
        await self.get(id)
        return False

    async def _update(self, id: Id, *conditions: object, **values: object) -> bool:
        table = AgentTurnRow.__table__
        result = await self.session.execute(
            update(table).where(table.c.id == id, *conditions).values(**values)  # type: ignore[arg-type]
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]


class SqlTurnProgress(TurnProgress):
    """Each write in a short transaction on a connection of its own (see the port), like
    SqlSourceCheckLog."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def start(self, id: Id, at: datetime) -> bool:
        async with AsyncSession(self.engine) as session, session.begin():
            return await SqlAgentTurnRepository(session).start(id, at)

    async def checkpoint(self, id: Id, parts: Sequence[TurnPart]) -> bool:
        async with AsyncSession(self.engine) as session, session.begin():
            turns = SqlAgentTurnRepository(session)
            return not await turns.save_parts(id, parts) or await turns.cancel_requested(id)

    async def running(self, id: Id) -> bool:
        async with AsyncSession(self.engine) as session:
            status = await session.scalar(select(AgentTurnRow.status).where(AgentTurnRow.id == id))
        if status is None:
            raise NotFound("agent turn", id)
        return status == TurnStatus.RUNNING.value

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn | None:
        async with AsyncSession(self.engine, expire_on_commit=False) as session, session.begin():
            return await SqlAgentTurnRepository(session).finish(id, status, parts, error, at)

    async def session_turns(self, id: Id) -> Sequence[AgentTurn]:
        async with AsyncSession(self.engine, expire_on_commit=False) as session, session.begin():
            turns = SqlAgentTurnRepository(session)
            return await turns.list((await turns.get(id)).session_id)

    async def abandon(self, id: Id, error: str, at: datetime) -> AgentTurn | None:
        async with AsyncSession(self.engine, expire_on_commit=False) as session, session.begin():
            turns = SqlAgentTurnRepository(session)
            if await turns.abandon(id, error, at):
                return await turns.get(id)
            await turns.get(id)
            return None
