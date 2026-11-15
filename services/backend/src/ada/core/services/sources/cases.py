"""The rules of cases sources (`access_kind: "cases"`): a case type's cases, step events or
results as an ordinary source. The address is the case type's id, `options.table` the
table (`ada.core.models.cases.CaseTable`). Reading them is ada.adapters.sources.cases;
saving a case marks them stale (ada.core.services.cases.service)."""

from ada.core.models.base import Id, JsonObject
from ada.core.models.cases import (
    CASE_TABLE_COLUMNS,
    CASE_TIME_COLUMN,
    CaseTable,
    CaseType,
    case_table,
    case_type_address,
    field_columns,
    result_column,
)
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, OutputKind, Roles, Schema, TimeRole
from ada.core.models.sources import AccessKind, DataSource, FreshnessKind, FreshnessPolicy
from ada.core.ports.repositories import CaseRepository, StatisticalModelRepository
from ada.core.services.statistical_models.kinds import KINDS

# Saving a case or storing a result refreshes them; nothing else needs to.
CASES_FRESHNESS = FreshnessPolicy(kind=FreshnessKind.PUSH)


async def case_type_of(cases: CaseRepository, project_id: Id, address: str) -> CaseType:
    """The case type a cases source reads, which must belong to the source's project."""
    case_type = await cases.get_type(case_type_address(address))
    if case_type.project_id != project_id:
        raise Invalid(f"The case type {case_type.id} belongs to another project")
    return case_type


async def case_schema(
    cases: CaseRepository,
    models: StatisticalModelRepository,
    project_id: Id,
    address: str,
    options: JsonObject,
    declared: Schema | None,
) -> Schema:
    """A cases source's declared schema: the table's columns, derived from the case type
    (and for results from the models on it), with the roles declared, if any, and the
    table's time column as the time role unless they name another."""
    case_type = await case_type_of(cases, project_id, address)
    table = case_table(options)
    columns = list(CASE_TABLE_COLUMNS[table])
    if table is CaseTable.CASES:
        columns.extend(field_columns(case_type.fields))
    elif table is CaseTable.RESULTS:
        columns.extend(await _result_columns(models, case_type))
    roles = declared.roles if declared is not None else Roles()
    if roles.time is None:
        time = CASE_TIME_COLUMN[table]
        roles = roles.model_copy(update={"time": TimeRole(start=time, end=time)})
    return Schema(kind=OutputKind.TABLE, columns=tuple(columns), roles=roles)


async def _result_columns(models: StatisticalModelRepository, case_type: CaseType) -> list[Column]:
    """The columns the latest version of each model on the case type can give, prefixed by
    its kind; one column per name, however many models of a kind there are."""
    found: dict[str, Column] = {}
    for model in await models.list(case_type.project_id):
        if model.case_type_id != case_type.id or model.kind not in KINDS:
            continue
        version = await models.version(model.id, model.latest_version)
        for column in KINDS[model.kind].columns(version):
            name = result_column(model.kind, column.name)
            found.setdefault(name, column.model_copy(update={"name": name}))
    return list(found.values())


def check_cases(source: DataSource, before: DataSource | None = None) -> None:
    """Raises Invalid for a cases source that cannot work. A cases source reads one table
    of one case type for good: its source operator keeps the columns it was registered
    with."""
    if source.access_kind is not AccessKind.CASES:
        return
    case_type_address(source.address)
    table = case_table(source.options)
    if before is not None and (
        case_type_address(before.address) != case_type_address(source.address)
        or case_table(before.options) is not table
    ):
        raise Invalid(
            "A cases source reads one table of one case type; to read another, register"
            " another source"
        )
