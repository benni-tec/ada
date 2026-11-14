"""Case types, cases, their step events and the results models produced for them."""

from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import add_row, dump, dump_all, fetch, oldest_first, require, rows
from ada.adapters.db.tables import (
    CaseEventRow,
    CaseResultRow,
    CaseRow,
    CaseTypeRow,
    ProjectRow,
)
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.cases import (
    Case,
    CaseEvent,
    CaseResult,
    CaseType,
    Field,
    ResultTrigger,
    Section,
)
from ada.core.ports.repositories import CaseRepository


class SqlCaseRepository(CaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_type(self, case_type: CaseType) -> None:
        await require(self.session, ProjectRow, case_type.project_id, "project")
        await add_row(
            self.session,
            CaseTypeRow(
                id=case_type.id,
                project_id=case_type.project_id,
                name=case_type.name,
                description=case_type.description,
                fields=dump_all(case_type.fields),
                revision=case_type.revision,
                created_by=dump(case_type.created_by),
                created_at=case_type.created_at,
            ),
        )

    async def get_type(self, id: Id) -> CaseType:
        return _type(await fetch(self.session, CaseTypeRow, id, "case type"))

    async def list_types(self, project_id: Id) -> Sequence[CaseType]:
        statement = oldest_first(CaseTypeRow, CaseTypeRow.project_id == project_id)
        return [_type(row) for row in await rows(self.session, statement)]

    async def update_type(self, case_type: CaseType) -> None:
        row = await fetch(self.session, CaseTypeRow, case_type.id, "case type")
        row.name = case_type.name
        row.description = case_type.description
        row.fields = dump_all(case_type.fields)
        row.revision = case_type.revision
        await self.session.flush()

    async def find(self, case_type_id: Id, key: str) -> Case | None:
        statement = select(CaseRow).where(CaseRow.case_type_id == case_type_id, CaseRow.key == key)
        row = (
            await self.session.execute(statement.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return None if row is None else _case(row)

    async def list(self, case_type_id: Id) -> Sequence[Case]:
        statement = oldest_first(CaseRow, CaseRow.case_type_id == case_type_id)
        return [_case(row) for row in await rows(self.session, statement)]

    async def count(self, case_type_id: Id) -> int:
        statement = (
            select(func.count()).select_from(CaseRow).where(CaseRow.case_type_id == case_type_id)
        )
        return int((await self.session.execute(statement)).scalar_one())

    async def add(self, case: Case) -> None:
        await require(self.session, CaseTypeRow, case.case_type_id, "case type")
        await add_row(
            self.session,
            CaseRow(
                id=case.id,
                case_type_id=case.case_type_id,
                key=case.key,
                values=case.values,
                schema_revision=case.schema_revision,
                revision=case.revision,
                created_at=case.created_at,
                updated_at=case.updated_at,
            ),
        )

    async def update(self, case: Case) -> None:
        row = await fetch(self.session, CaseRow, case.id, "case")
        row.values = case.values
        row.schema_revision = case.schema_revision
        row.revision = case.revision
        row.updated_at = case.updated_at
        await self.session.flush()

    async def add_events(self, events: Sequence[CaseEvent]) -> None:
        for event in events:
            self.session.add(
                CaseEventRow(
                    case_id=event.case_id,
                    field=event.field,
                    step=event.step,
                    days=event.days,
                    recorded_at=event.recorded_at,
                )
            )
        await self.session.flush()

    async def events(self, case_id: Id) -> Sequence[CaseEvent]:
        statement = (
            select(CaseEventRow)
            .where(CaseEventRow.case_id == case_id)
            .order_by(CaseEventRow.recorded_at, CaseEventRow.id)
        )
        return [
            CaseEvent(
                case_id=row.case_id,
                field=row.field,
                step=row.step,
                days=row.days,
                recorded_at=row.recorded_at,
            )
            for row in await rows(self.session, statement)
        ]

    async def add_result(self, result: CaseResult) -> None:
        await add_row(
            self.session,
            CaseResultRow(
                id=result.id,
                case_id=result.case_id,
                model_id=result.model_id,
                version=result.version,
                case_revision=result.case_revision,
                section=dump(result.section),
                trigger=result.trigger.value,
                created_by=dump(result.created_by),
                created_at=result.created_at,
            ),
        )

    async def results(self, case_id: Id) -> Sequence[CaseResult]:
        statement = (
            select(CaseResultRow)
            .where(CaseResultRow.case_id == case_id)
            .order_by(CaseResultRow.created_at.desc(), CaseResultRow.id.desc())
        )
        return [_result(row) for row in await rows(self.session, statement)]

    async def latest_results(self, model_id: Id) -> Mapping[Id, CaseResult]:
        statement = (
            select(CaseResultRow)
            .where(CaseResultRow.model_id == model_id)
            .order_by(CaseResultRow.created_at, CaseResultRow.id)
        )
        latest: dict[Id, CaseResult] = {}
        for row in await rows(self.session, statement):
            latest[row.case_id] = _result(row)
        return latest

    async def result_counts(self, model_id: Id) -> Mapping[Id, int]:
        statement = (
            select(CaseResultRow.case_id, func.count())
            .where(CaseResultRow.model_id == model_id)
            .group_by(CaseResultRow.case_id)
        )
        return {case_id: int(n) for case_id, n in (await self.session.execute(statement)).all()}


def _type(row: CaseTypeRow) -> CaseType:
    return CaseType(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        fields=tuple(Field.model_validate(f) for f in row.fields),
        revision=row.revision,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )


def _case(row: CaseRow) -> Case:
    return Case(
        id=row.id,
        case_type_id=row.case_type_id,
        key=row.key,
        values=row.values,
        schema_revision=row.schema_revision,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _result(row: CaseResultRow) -> CaseResult:
    return CaseResult(
        id=row.id,
        case_id=row.case_id,
        model_id=row.model_id,
        version=row.version,
        case_revision=row.case_revision,
        section=Section.model_validate(row.section),
        trigger=ResultTrigger(row.trigger),
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )
