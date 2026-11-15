"""The demo's curated dashboards, replayed from the fixture `demo.json` (written by
`scripts/export_demo.py` from the instance they were built on): the National Cancer
Strategy's four goals with their alert rules, the pathway times of the synthetic cases, and
the data quality of the county indicators, with every operator and data source behind them.

The cases they read come first: the patient pathway model (which brings the "Suspected cancer
pathway" case type) and synthetic cases on it. Everything is found by name or identity and
only what is missing is added, so seeding again changes nothing.
"""

import json
import random
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from dishka import AsyncContainer

from ada.core.models.actors import Actor
from ada.core.models.alerts import Severity
from ada.core.models.base import Id
from ada.core.models.dashboards import Slot
from ada.core.models.schema import Roles, Schema
from ada.core.models.sources import AccessKind, DataFormat, FreshnessPolicy, Provenance
from ada.core.models.time import TimeRange
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.cases import CaseService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.synthetic import case, typical_days

FIXTURE = Path(__file__).with_name("demo.json")
PATHWAY_KIND = "patient_pathway"
SYNTHETIC_CASES = 300
# The dashboards pinned to the top of the sidebar, in this order.
PINNED = ("National Cancer Strategy 2026–2035", "Pathway times by county (synthetic)")


async def seed_cases(container: AsyncContainer, project_id: Id, actor: Actor) -> dict[str, Id]:
    """The pathway model and its case type, with synthetic cases the first time. Answers the
    project's case types by name."""
    async with container() as request:
        models = await request.get(StatisticalModelService)
        if not any(model.kind == PATHWAY_KIND for model in await models.list(project_id)):
            await models.create_pathway_model(project_id, actor)
            print("  created the patient pathway model")
    async with container() as request:
        models = await request.get(StatisticalModelService)
        cases = await request.get(CaseService)
        model = next(m for m in await models.list(project_id) if m.kind == PATHWAY_KIND)
        assert model.case_type_id is not None, "the pathway model brings its case type"
        if not await cases.list_cases(model.case_type_id):
            version = (await models.version(model.id)).model_dump(mode="json")
            centres, rng, today = typical_days(version), random.Random(1), date.today()
            for n in range(1, SYNTHETIC_CASES + 1):
                key, values = case(rng, n, centres, today, 18)
                await cases.put_case(model.case_type_id, key, values, actor)
            print(f"  put {SYNTHETIC_CASES} synthetic cases")
        return {t.name: t.id for t in await cases.list_types(project_id)}


async def seed_curated(
    container: AsyncContainer, project_id: Id, case_types: dict[str, Id], actor: Actor
) -> Sequence[Id]:
    """Replay the dashboards the project lacks. Answers the data sources it registered, for
    the caller to fetch."""
    fixture: dict[str, Any] = json.loads(FIXTURE.read_text())
    async with container() as request:
        dashboards = await request.get(DashboardService)
        existing = {d.name for d in await dashboards.list(project_id)}
        wanted = [d for d in fixture["dashboards"] if d["name"] not in existing]
        if not wanted:
            print("  the curated dashboards exist")
            return []
        sources = await request.get(SourceService)
        pipelines = await request.get(PipelineService)
        widgets = await request.get(WidgetService)
        alerts = await request.get(AlertService)

        # The data sources, reused where one of that name reads the same address.
        known = {(s.name, s.address): s for s in await sources.list(project_id)}
        source_ids: dict[str, Id] = {}
        added: list[Id] = []
        for key, registration in fixture["sources"].items():
            address = registration["address"]
            if registration["access_kind"] == AccessKind.CASES:
                address = str(case_types[fixture["case_types"][address]])
            source = known.get((registration["name"], address))
            if source is None:
                source = await sources.register(
                    project_id,
                    registration["name"],
                    AccessKind(registration["access_kind"]),
                    address,
                    DataFormat(registration["format"]),
                    options=registration["options"],
                    freshness=_model(FreshnessPolicy, registration["freshness"]),
                    declared_schema=_model(Schema, registration["declared_schema"]),
                    provenance=_model(Provenance, registration["provenance"]),
                )
                added.append(source.id)
            source_ids[key] = source.id

        # The operators, inputs first; adding one that exists returns it.
        operators: dict[str, str] = {}
        for operator in fixture["operators"]:
            if operator["kind"] == "source":
                made = await pipelines.add_source(project_id, source_ids[operator["source"]], actor)
            else:
                made = await pipelines.add_transform(
                    project_id,
                    operator["sql"],
                    [operators[input] for input in operator["inputs"]],
                    actor,
                    roles=_model(Roles, operator["roles"]),
                    materialize=operator["materialize"],
                )
            operators[operator["key"]] = made.id

        for spec in wanted:
            slots = []
            for slot in spec["slots"]:
                widget = fixture["widgets"][slot["widget"]]
                made = await widgets.create(
                    project_id,
                    operators[widget["operator_id"]],
                    widget["type"],
                    widget["title"],
                    actor,
                    spec=widget["spec"],
                    note=widget["note"],
                    inputs={name: operators[op] for name, op in widget["inputs"].items()},
                )
                slots.append(
                    Slot(
                        name=slot["name"],
                        description=slot["description"],
                        widget_id=made.id,
                        layout=slot["layout"],
                    )
                )
            dashboard = await dashboards.create(project_id, spec["name"], actor)
            await dashboards.edit(dashboard.id, slots, dashboard.revision, actor)
            dashboard = await dashboards.get(dashboard.id)
            time_range = TimeRange.model_validate(spec["default_time_range"])
            if time_range != TimeRange():
                await dashboards.set_default_time_range(
                    dashboard.id, time_range, dashboard.revision
                )
            for rule in spec["rules"]:
                await alerts.create_rule(
                    dashboard.id,
                    rule["name"],
                    operators[rule["operator_id"]],
                    rule["formula"],
                    rule["key_columns"],
                    severity=Severity(rule["severity"]),
                    check_interval_seconds=rule["check_interval_seconds"],
                    max_data_age_seconds=rule["max_data_age_seconds"],
                )
            counts = f"{len(slots)} widgets, {len(spec['rules'])} rules"
            print(f"  dashboard {dashboard.id}  {spec['name']} ({counts})")

        by_name = {d.name: d.id for d in await dashboards.list(project_id)}
        await dashboards.reorder(project_id, [by_name[name] for name in PINNED if name in by_name])
        return added


def _model[M](model: type[M], value: Any) -> M | None:
    return None if value is None else model.model_validate(value)  # type: ignore[attr-defined]
