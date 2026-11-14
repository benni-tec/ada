"""Case types and cases, and running the models on a case's type."""

from collections.abc import Sequence
from functools import partial
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.cases import (
    Case,
    CaseEvent,
    CaseResult,
    CaseState,
    CaseType,
    CaseWithResult,
    Field,
    FieldType,
    ModelOnCase,
    ResultTrigger,
    SavedCase,
    Section,
)
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.sources import AccessKind, FreshnessKind
from ada.core.models.statistical_models import StatisticalModel
from ada.core.ports.repositories import (
    CaseRepository,
    DataSourceRepository,
    StatisticalModelRepository,
)
from ada.core.ports.system import Clock
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.cases.fields import (
    check_fields,
    check_key,
    check_values,
    compatible,
    coverage,
    describe,
)
from ada.core.services.cases.models import adapter
from ada.core.services.ports.cases import CaseService
from ada.core.services.statistical_models import pathway

# How urgent a result is, most urgent first, for the open-case list.
URGENCY = {"urgent": 0, "warn": 1, "info": 2, "ok": 3}


class Cases(CaseService):
    def __init__(
        self,
        cases: CaseRepository,
        models: StatisticalModelRepository,
        clock: Clock,
        sources: DataSourceRepository,
        dispatcher: TaskDispatcher,
        after_commit: AfterCommit,
    ) -> None:
        self.cases = cases
        self.statistical = models
        self.clock = clock
        self.sources = sources
        self.dispatcher = dispatcher
        self.after_commit = after_commit
        # The case types whose sources this unit of work has marked stale already.
        self._changed: set[Id] = set()

    async def create_type(
        self, project_id: Id, name: str, description: str, fields: tuple[Field, ...], actor: Actor
    ) -> CaseType:
        if not name.strip():
            raise Invalid("A case type needs a name")
        check_fields(fields)
        case_type = CaseType(
            id=uuid7(),
            project_id=project_id,
            name=name,
            description=description,
            fields=fields,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.cases.add_type(case_type)
        return case_type

    async def update_type(
        self,
        id: Id,
        name: str | None = None,
        description: str | None = None,
        fields: tuple[Field, ...] | None = None,
    ) -> CaseType:
        case_type = await self.cases.get_type(id)
        update: dict[str, object] = {}
        if name is not None:
            if not name.strip():
                raise Invalid("A case type needs a name")
            update["name"] = name
        if description is not None:
            update["description"] = description
        if fields is not None and fields != case_type.fields:
            check_fields(fields)
            if await self.cases.count(id):
                problems = compatible(case_type.fields, fields)
                if problems:
                    raise Invalid(
                        "This case type has cases, so its fields can only grow: "
                        + "; ".join(problems)
                    )
            for model in await self._on_type(case_type):
                version = await self.statistical.version(model.id, model.latest_version)
                gaps = coverage(fields, adapter(model.kind).requires(version))
                if gaps:
                    raise Invalid(f"{model.name} would no longer be covered: {describe(gaps)}")
            update["fields"] = fields
            update["revision"] = case_type.revision + 1
        changed = case_type.model_copy(update=update)
        await self.cases.update_type(changed)
        return changed

    async def get_type(self, id: Id) -> CaseType:
        return await self.cases.get_type(id)

    async def list_types(self, project_id: Id) -> Sequence[CaseType]:
        return await self.cases.list_types(project_id)

    async def put_case(
        self, case_type_id: Id, key: str, values: JsonObject, actor: Actor
    ) -> SavedCase:
        case_type = await self.cases.get_type(case_type_id)
        check_key(key)
        checked = check_values(case_type.fields, values)
        now = self.clock.now()
        before = await self.cases.find(case_type_id, key)
        if before is None:
            case = Case(
                id=uuid7(),
                case_type_id=case_type_id,
                key=key,
                values=checked,
                schema_revision=case_type.revision,
                created_at=now,
                updated_at=now,
            )
            await self.cases.add(case)
        else:
            case = before.model_copy(
                update={
                    "values": checked,
                    "schema_revision": case_type.revision,
                    "revision": before.revision + 1,
                    "updated_at": now,
                }
            )
            await self.cases.update(case)
        await self.cases.add_events(
            _changed_steps(case_type, before.values if before else {}, case)
        )
        await self._stale(case_type.id)
        ran: list[Id] = []
        for model in await self._on_type(case_type):
            if model.auto_run:
                await self._run(model, case, ResultTrigger.AUTO, actor)
                ran.append(model.id)
        state = await self._state(case)
        return SavedCase(**state.model_dump(), ran=tuple(ran))

    async def get_case(self, case_type_id: Id, key: str) -> CaseState:
        return await self._state(await self._case(case_type_id, key))

    async def list_cases(self, case_type_id: Id) -> Sequence[Case]:
        await self.cases.get_type(case_type_id)
        return await self.cases.list(case_type_id)

    async def models(self, case_type_id: Id, key: str) -> Sequence[ModelOnCase]:
        case = await self._case(case_type_id, key)
        results = await self.cases.results(case.id)
        out = []
        for model in await self._on_type(await self.cases.get_type(case_type_id)):
            mine = [r for r in results if r.model_id == model.id]
            out.append(
                ModelOnCase(
                    model_id=model.id,
                    name=model.name,
                    kind=model.kind,
                    version=model.latest_version,
                    auto_run=model.auto_run,
                    latest=mine[0] if mine else None,
                    results=len(mine),
                )
            )
        return out

    async def evaluate(self, case_type_id: Id, key: str, model_id: Id, actor: Actor) -> CaseResult:
        case = await self._case(case_type_id, key)
        model = await self.statistical.get(model_id)
        if model.case_type_id != case_type_id:
            raise Invalid(f"{model.name} does not run on this case type")
        return await self._run(model, case, ResultTrigger.REQUEST, actor)

    async def open_cases(self, case_type_id: Id) -> Sequence[CaseWithResult]:
        case_type = await self.cases.get_type(case_type_id)
        pathways = [m for m in await self._on_type(case_type) if m.kind == pathway.KIND]
        latest: dict[Id, CaseResult] = {}
        for model in pathways:
            for case_id, result in (await self.cases.latest_results(model.id)).items():
                if case_id not in latest or result.created_at > latest[case_id].created_at:
                    latest[case_id] = result
        open_ = [
            CaseWithResult(case=case, latest=latest[case.id])
            for case in await self.cases.list(case_type_id)
            if case.id in latest and _open(latest[case.id].section)
        ]
        return sorted(open_, key=_urgency)

    async def model_cases(self, model_id: Id) -> Sequence[CaseWithResult]:
        model = await self.statistical.get(model_id)
        if model.case_type_id is None:
            return []
        latest = await self.cases.latest_results(model_id)
        return [
            CaseWithResult(case=case, latest=latest.get(case.id))
            for case in await self.cases.list(model.case_type_id)
        ]

    async def _case(self, case_type_id: Id, key: str) -> Case:
        case = await self.cases.find(case_type_id, key)
        if case is None:
            raise NotFound("case", key)
        return case

    async def _state(self, case: Case) -> CaseState:
        return CaseState(
            case=case,
            events=tuple(await self.cases.events(case.id)),
            results=tuple(await self.cases.results(case.id)),
        )

    async def _on_type(self, case_type: CaseType) -> list[StatisticalModel]:
        return [
            m
            for m in await self.statistical.list(case_type.project_id)
            if m.case_type_id == case_type.id
        ]

    async def _run(
        self, model: StatisticalModel, case: Case, trigger: ResultTrigger, actor: Actor
    ) -> CaseResult:
        version = await self.statistical.version(model.id, model.latest_version)
        kind = adapter(model.kind)
        needs = {f.name for f in kind.requires(version)}
        values = {k: v for k, v in case.values.items() if k in needs}
        try:
            section = kind.run(version, values)
        except Invalid as error:
            section = Section(
                kind=model.kind, title=model.name, summary=f"Could not run: {error}", status="warn"
            )
        result = CaseResult(
            id=uuid7(),
            case_id=case.id,
            model_id=model.id,
            version=version.version,
            case_revision=case.revision,
            section=section,
            trigger=trigger,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.cases.add_result(result)
        await self._stale(case.case_type_id)
        return result

    async def _stale(self, case_type_id: Id) -> None:
        """Mark the cases sources on the type stale: each one kept fresh by push gets a
        forced refresh once this unit of work has committed, as a watched page's webhook
        queues one. Once per type and unit of work, however many cases or results it
        stores."""
        if case_type_id in self._changed:
            return
        self._changed.add(case_type_id)
        case_type = await self.cases.get_type(case_type_id)
        for source in await self.sources.list(case_type.project_id):
            if (
                source.access_kind is AccessKind.CASES
                and source.address == str(case_type_id)
                and source.freshness.kind is FreshnessKind.PUSH
            ):
                self.after_commit.add(partial(self.dispatcher.refresh_source, source.id, True))


def _changed_steps(case_type: CaseType, before: JsonObject, case: Case) -> list[CaseEvent]:
    """An event for every step of a day-map field whose days are new or changed."""
    events = []
    for f in case_type.fields:
        if f.type is not FieldType.DAY_MAP:
            continue
        old = before.get(f.name) or {}
        for step, days in (case.values.get(f.name) or {}).items():
            if old.get(step) != days:
                events.append(
                    CaseEvent(
                        case_id=case.id,
                        field=f.name,
                        step=step,
                        days=days,
                        recorded_at=case.updated_at,
                    )
                )
    return events


def _open(section: Section) -> bool:
    """Open until treatment has started: its deadline met or late, or no pathway at all."""
    status = section.columns.get("treatment_start_status")
    return section.columns.get("trigger") != "none" and status not in ("met", "late")


def _urgency(item: CaseWithResult) -> tuple[int, int]:
    assert item.latest is not None
    section = item.latest.section
    overdue = max(
        (
            int(v)
            for k, v in section.columns.items()
            if k.endswith("_by")
            and section.columns.get(k.removesuffix("_by") + "_status") == "overdue"
            and isinstance(v, int)
        ),
        default=0,
    )
    return URGENCY.get(section.status, 9), -overdue
