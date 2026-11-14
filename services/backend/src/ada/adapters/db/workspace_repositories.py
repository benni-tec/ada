"""Repositories of what a person sets up: projects, data sources, sessions and widgets."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ada.adapters.db.support import (
    add_row,
    dump,
    fetch,
    json_object,
    oldest_first,
    require,
    rows,
    update_row,
)
from ada.adapters.db.tables import (
    DataSourceRow,
    OperatorRow,
    ProjectRow,
    SessionEntryRow,
    SessionRow,
    WidgetRow,
)
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import NotFound
from ada.core.models.projects import Project
from ada.core.models.schema import Schema
from ada.core.models.sessions import EntryKind, Session, SessionEntry
from ada.core.models.sources import AccessKind, DataFormat, DataSource, FreshnessPolicy
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import (
    DataSourceRepository,
    ProjectRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.sources import SourceCheckLog, SourceLocks


def _project(row: ProjectRow) -> Project:
    return Project(id=row.id, name=row.name, created_at=row.created_at, revision=row.revision)


class SqlProjectRepository(ProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Project:
        return _project(await fetch(self.session, ProjectRow, id, "project"))

    async def list(self) -> Sequence[Project]:
        return [_project(row) for row in await rows(self.session, oldest_first(ProjectRow))]

    async def add(self, project: Project) -> None:
        row = ProjectRow(id=project.id, name=project.name, created_at=project.created_at)
        await add_row(self.session, row)

    async def update(self, project: Project, expected_revision: int) -> Project:
        row = await update_row(
            self.session,
            ProjectRow,
            "project",
            project.id,
            expected_revision,
            {"name": project.name},
        )
        return _project(row)


def _data_source(row: DataSourceRow) -> DataSource:
    return DataSource(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        access_kind=AccessKind(row.access_kind),
        address=row.address,
        format=DataFormat(row.format),
        options=row.options,
        freshness=FreshnessPolicy.model_validate(row.freshness),
        declared_schema=(
            Schema.model_validate(row.declared_schema) if row.declared_schema is not None else None
        ),
        created_at=row.created_at,
        last_checked_at=row.last_checked_at,
        last_probe_token=row.last_probe_token,
        last_error=row.last_error,
        revision=row.revision,
    )


def _data_source_edit(source: DataSource) -> dict[str, object]:
    """The columns an edit may change. The last_* columns are written by refreshes alone
    (`record_check`): an edit that read the source before a refresh must not put the old
    outcome back."""
    return {
        "name": source.name,
        "access_kind": source.access_kind.value,
        "address": source.address,
        "format": source.format.value,
        "options": json_object(source.options),
        "freshness": dump(source.freshness),
        "declared_schema": dump(source.declared_schema) if source.declared_schema else None,
    }


class SqlDataSourceRepository(DataSourceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> DataSource:
        return _data_source(await fetch(self.session, DataSourceRow, id, "data source"))

    async def list(self, project_id: Id) -> Sequence[DataSource]:
        statement = oldest_first(DataSourceRow, DataSourceRow.project_id == project_id)
        return [_data_source(row) for row in await rows(self.session, statement)]

    async def list_all(self) -> Sequence[DataSource]:
        return [_data_source(row) for row in await rows(self.session, oldest_first(DataSourceRow))]

    async def add(self, source: DataSource) -> None:
        row = DataSourceRow(
            id=source.id,
            project_id=source.project_id,
            created_at=source.created_at,
            last_checked_at=source.last_checked_at,
            last_probe_token=source.last_probe_token,
            last_error=source.last_error,
            **_data_source_edit(source),
        )
        await add_row(self.session, row)

    async def update(self, source: DataSource, expected_revision: int) -> DataSource:
        row = await update_row(
            self.session,
            DataSourceRow,
            "data source",
            source.id,
            expected_revision,
            _data_source_edit(source),
        )
        return _data_source(row)

    async def record_check(
        self, id: Id, at: datetime, probe_token: str | None, error: str | None
    ) -> None:
        # A plain UPDATE on the table: going through the ORM would count the revision up,
        # and a refresh must never make a concurrent edit conflict.
        table = DataSourceRow.__table__
        result = await self.session.execute(
            update(table)
            .where(table.c.id == id)
            .values(last_checked_at=at, last_probe_token=probe_token, last_error=error)
        )
        if result.rowcount == 0:
            raise NotFound("data source", id)


def _session(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        origin_dashboard_id=row.origin_dashboard_id,
        panel_dashboard_id=row.panel_dashboard_id,
        created_at=row.created_at,
        revision=row.revision,
    )


def _entry(row: SessionEntryRow) -> SessionEntry:
    return SessionEntry(
        id=row.id,
        session_id=row.session_id,
        kind=EntryKind(row.kind),
        text=row.text,
        ref=row.ref,
        actor=Actor.model_validate(row.actor),
        created_at=row.created_at,
    )


class SqlSessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Session:
        return _session(await fetch(self.session, SessionRow, id, "session"))

    async def list(self, project_id: Id) -> Sequence[Session]:
        statement = oldest_first(SessionRow, SessionRow.project_id == project_id)
        return [_session(row) for row in await rows(self.session, statement)]

    async def add(self, session: Session) -> None:
        row = SessionRow(
            id=session.id,
            project_id=session.project_id,
            title=session.title,
            origin_dashboard_id=session.origin_dashboard_id,
            panel_dashboard_id=session.panel_dashboard_id,
            created_at=session.created_at,
        )
        await add_row(self.session, row)

    async def update(self, session: Session, expected_revision: int) -> Session:
        row = await update_row(
            self.session,
            SessionRow,
            "session",
            session.id,
            expected_revision,
            {
                "title": session.title,
                "origin_dashboard_id": session.origin_dashboard_id,
                "panel_dashboard_id": session.panel_dashboard_id,
            },
        )
        return _session(row)

    async def add_entry(self, entry: SessionEntry) -> None:
        await require(self.session, SessionRow, entry.session_id, "session")
        row = SessionEntryRow(
            id=entry.id,
            session_id=entry.session_id,
            kind=entry.kind.value,
            text=entry.text,
            ref=entry.ref,
            actor=dump(entry.actor),
            created_at=entry.created_at,
        )
        await add_row(self.session, row)

    async def entries(self, session_id: Id) -> Sequence[SessionEntry]:
        statement = oldest_first(SessionEntryRow, SessionEntryRow.session_id == session_id)
        return [_entry(row) for row in await rows(self.session, statement)]


def _widget(row: WidgetRow) -> Widget:
    return Widget(
        id=row.id,
        project_id=row.project_id,
        session_id=row.session_id,
        operator_id=row.operator_id,
        type=row.type,
        title=row.title,
        spec=row.spec,
        note=row.note,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )


class SqlWidgetRepository(WidgetRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Widget:
        return _widget(await fetch(self.session, WidgetRow, id, "widget"))

    async def add(self, widget: Widget) -> None:
        await require(self.session, OperatorRow, widget.operator_id, "operator")
        row = WidgetRow(
            id=widget.id,
            project_id=widget.project_id,
            session_id=widget.session_id,
            operator_id=widget.operator_id,
            type=widget.type,
            title=widget.title,
            spec=json_object(widget.spec),
            note=widget.note,
            created_by=dump(widget.created_by),
            created_at=widget.created_at,
        )
        await add_row(self.session, row)

    async def list(self, project_id: Id) -> Sequence[Widget]:
        statement = oldest_first(WidgetRow, WidgetRow.project_id == project_id)
        return [_widget(row) for row in await rows(self.session, statement)]

    async def list_by_session(self, session_id: Id) -> Sequence[Widget]:
        statement = oldest_first(WidgetRow, WidgetRow.session_id == session_id)
        return [_widget(row) for row in await rows(self.session, statement)]


class SqlSourceLocks(SourceLocks):
    """A transaction-level advisory lock per data source on the request's session: it is
    released when the unit of work commits or rolls back, never left behind."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def hold(self, id: Id) -> None:
        # Advisory locks take a 64-bit key; the first half of the UUIDv7 is its time and
        # randomness enough to keep two sources apart in practice.
        key = int.from_bytes(id.bytes[:8], "big", signed=True)
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


class SqlSourceCheckLog(SourceCheckLog):
    """Records a failed refresh in a short transaction on a connection of its own.

    The request's session is not used, so the record survives its rollback. It cannot wait
    on that session's locks either: a refresh only reads the data source row before it
    fails, and nothing else in a refresh writes it."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def record_failure(
        self, id: Id, at: datetime, probe_token: str | None, error: str
    ) -> None:
        async with AsyncSession(self.engine) as session, session.begin():
            await SqlDataSourceRepository(session).record_check(id, at, probe_token, error)
