"""Knowing an operator's columns before anything runs, and checking declarations against
them."""

from collections.abc import Iterable

from ada.core.models.errors import Invalid
from ada.core.models.operators import Operator, OperatorKind, SourceParams
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Column, ColumnType, Roles, Schema
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.repositories import OperatorRepository, SnapshotRepository
from ada.core.services.pipelines.fusion import Node, SnapshotNode, StandInNode, compose
from ada.core.services.ports.sources import SourceService

# Source snapshots carry no parameters in wave 1: there is no time-range pushdown yet.
SOURCE_KEY = ""

_NUMERIC = {ColumnType.INTEGER, ColumnType.NUMBER}


class Columns:
    """Works out the columns an operator produces. Declared or derived columns are on the
    operator already; a source registered without a schema has the columns of its data,
    so its current snapshot is described, after a first refresh if it has none."""

    def __init__(
        self,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        sources: SourceService,
        store: AnalysisStore,
    ) -> None:
        self.operators = operators
        self.snapshots = snapshots
        self.sources = sources
        self.store = store

    async def of(self, operator: Operator) -> tuple[Column, ...]:
        if operator.output.columns:
            return operator.output.columns
        return await self.store.describe(compose(await self.node(operator)))

    async def node(self, operator: Operator) -> Node:
        """What stands for the operator when a query over it is described: its columns
        with no rows where they are known, so describing needs no data; otherwise the
        source's stored data."""
        if operator.output.columns:
            return StandInNode(operator.output.columns)
        if operator.kind is OperatorKind.SOURCE:
            return SnapshotNode(await self.source_snapshot(operator))
        if operator.kind is OperatorKind.INPUT and operator.inputs:
            return await self.node(await self.operators.get(operator.inputs[0]))
        raise Invalid(f"The columns of operator {operator.id} are not known")

    async def source_snapshot(self, operator: Operator) -> Snapshot:
        snapshot = await self.snapshots.current(operator.id, SOURCE_KEY)
        if snapshot is None:
            await self.sources.refresh(SourceParams.model_validate(operator.params).data_source_id)
            snapshot = await self.snapshots.current(operator.id, SOURCE_KEY)
        if snapshot is None:
            raise Invalid(f"The source of operator {operator.id} has no data yet")
        return snapshot


def check_unique(columns: tuple[Column, ...]) -> None:
    names = [column.name for column in columns]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise Invalid(f"Column names must be unique; repeated: {', '.join(repeated)}")


def check_roles(roles: Roles, columns: tuple[Column, ...]) -> None:
    """Roles must name columns that exist and whose types fit what the role means: a
    measure and its bounds are numbers, a suppression flag is a boolean."""
    by_name = {column.name: column for column in columns}
    problems: list[str] = []

    def need(name: str, role: str, types: set[ColumnType] | None = None) -> None:
        column = by_name.get(name)
        if column is None:
            problems.append(f"{role} names {name!r}, which is not a column")
        elif types is not None and column.type not in types:
            problems.append(f"{role} needs {name!r} to be {_one_of(types)}, not {column.type}")

    if roles.time:
        need(roles.time.start, "the time start")
        need(roles.time.end, "the time end")
    if roles.geo:
        need(roles.geo.code, "the region code")
    for measure in roles.measures:
        need(measure.value, "a measure", _NUMERIC)
        for name, role in (
            (measure.lower, "a lower bound"),
            (measure.upper, "an upper bound"),
            (measure.coverage, "a coverage"),
        ):
            if name is not None:
                need(name, role, _NUMERIC)
        if measure.suppressed is not None:
            need(measure.suppressed, "a suppression flag", {ColumnType.BOOLEAN})
    if problems:
        raise Invalid("The roles do not fit the columns: " + "; ".join(problems))


def check_fits(slot: Schema, columns: tuple[Column, ...], what: str) -> None:
    """Whether data with `columns` can fill a slot declared as `slot`: every declared
    column must be there with a fitting type. Extra columns are allowed; an integer
    fits where a number is declared."""
    by_name = {column.name: column for column in columns}
    problems: list[str] = []
    for wanted in slot.columns:
        actual = by_name.get(wanted.name)
        if actual is None:
            problems.append(f"{wanted.name!r} is missing")
        elif not _fits(wanted.type, actual.type):
            problems.append(f"{wanted.name!r} is {actual.type}, not {wanted.type}")
    if problems:
        raise Invalid(f"{what} does not match the slot's schema: " + "; ".join(problems))


def check_still_matches(declared: tuple[Column, ...], actual: Iterable[Column], what: str) -> None:
    """The run-time half of validating a declaration: the output must still have every
    column the operator states, e.g. after a source changed its shape."""
    present = {column.name for column in actual}
    missing = [column.name for column in declared if column.name not in present]
    if missing:
        raise Invalid(f"{what} no longer returns the columns it states: {', '.join(missing)}")


def _fits(wanted: ColumnType, actual: ColumnType) -> bool:
    return wanted == actual or (wanted is ColumnType.NUMBER and actual is ColumnType.INTEGER)


def _one_of(types: set[ColumnType]) -> str:
    return " or ".join(sorted(t.value for t in types))
