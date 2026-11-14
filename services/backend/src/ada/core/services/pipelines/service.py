from collections.abc import Sequence

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.operators import (
    HistoryParams,
    InputParams,
    Operator,
    OperatorId,
    OperatorKind,
    SourceParams,
    TransformParams,
    operator_identity,
)
from ada.core.models.pipelines import Pipeline
from ada.core.models.schema import Column, ColumnType, OutputKind, Roles, Schema
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    SnapshotRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.pipelines import listing
from ada.core.services.pipelines.fusion import QueryNode, SnapshotNode, compose
from ada.core.services.pipelines.schemas import (
    SOURCE_KEY,
    Columns,
    check_fits,
    check_unique,
)
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.sources import SourceService
from ada.core.services.schema.intervals import check_bounds
from ada.core.services.schema.roles import check_compatible, check_roles


class Pipelines(PipelineService):
    """Adds operators. Each is looked up by its identity first, so a repeated definition
    costs one read and returns what is stored; only a new one has its schema worked out."""

    def __init__(
        self,
        operators: OperatorRepository,
        data_sources: DataSourceRepository,
        snapshots: SnapshotRepository,
        sources: SourceService,
        store: AnalysisStore,
        clock: Clock,
    ) -> None:
        self.operators = operators
        self.data_sources = data_sources
        self.store = store
        self.clock = clock
        self.columns = Columns(operators, snapshots, sources, store)

    async def add_source(self, project_id: Id, data_source_id: Id, actor: Actor) -> Operator:
        # The same definition SourceService.register adds, so this usually finds it.
        params = SourceParams(data_source_id=data_source_id).model_dump(mode="json")
        id = operator_identity(project_id, OperatorKind.SOURCE, params, ())
        if existing := await self._find(id):
            return existing
        source = await self.data_sources.get(data_source_id)
        if source.project_id != project_id:
            raise Invalid(f"Data source {data_source_id} belongs to another project")
        operator = Operator(
            id=id,
            project_id=project_id,
            kind=OperatorKind.SOURCE,
            params=params,
            output=source.declared_schema or Schema(),
            materializing=True,
            created_by=actor,
            created_at=self.clock.now(),
        )
        return await self.operators.add(operator)

    async def add_history(
        self, project_id: Id, source_id: Id, actor: Actor, last: int = 10
    ) -> Operator:
        if isinstance(last, bool) or not isinstance(last, int) or last < 1:
            raise Invalid("History last must be a positive integer")
        source = await self.data_sources.get(source_id)
        if source.project_id != project_id:
            raise Invalid(f"Data source {source_id} belongs to another project")
        if source.options.get("pushdown") is not None:
            raise Invalid("Source history does not support period (pushdown) sources")
        upstream = await self.add_source(project_id, source_id, actor)
        if upstream.output.kind is not OutputKind.TABLE:
            raise Invalid("Source history needs a source that produces a table")
        params = HistoryParams(last=last).model_dump(mode="json")
        id = operator_identity(project_id, OperatorKind.HISTORY, params, (upstream.id,))
        if existing := await self._find(id):
            return existing
        anchor = await self.columns.source_snapshot(upstream)
        snapshots = sorted(
            (
                s
                for s in await self.columns.snapshots.list(upstream.id)
                if s.parameters_key == SOURCE_KEY
                and (s.fetched_at, s.id) <= (anchor.fetched_at, anchor.id)
            ),
            key=lambda s: (s.fetched_at, s.id),
            reverse=True,
        )[:last]
        columns = await self.store.describe(
            compose(
                QueryNode(
                    id,
                    " UNION ALL BY NAME ".join(
                        f"SELECT * FROM input_{i}" for i in range(len(snapshots))
                    ),
                    tuple(SnapshotNode(s) for s in snapshots),
                )
            )
        )
        if any(c.name.lower() in {"snapshot_at", "snapshot_rank"} for c in columns):
            raise Invalid("Source history reserves the columns snapshot_at and snapshot_rank")
        return await self.operators.add(
            Operator(
                id=id,
                project_id=project_id,
                kind=OperatorKind.HISTORY,
                params=params,
                inputs=(upstream.id,),
                output=Schema(
                    columns=columns
                    + (
                        Column(name="snapshot_at", type=ColumnType.TIMESTAMP),
                        Column(name="snapshot_rank", type=ColumnType.INTEGER),
                    )
                ),
                materializing=False,
                created_by=actor,
                created_at=self.clock.now(),
            )
        )

    async def describe(
        self, project_id: Id, sql: str, inputs: Sequence[OperatorId]
    ) -> tuple[Column, ...]:
        upstream = [await self._upstream(project_id, input_id) for input_id in inputs]
        nodes = tuple([await self.columns.node(operator) for operator in upstream])
        columns = await self.store.describe(compose(QueryNode("described", sql, nodes)))
        check_unique(columns)
        return columns

    async def add_transform(
        self,
        project_id: Id,
        sql: str,
        inputs: Sequence[OperatorId],
        actor: Actor,
        roles: Roles | None = None,
        materialize: bool = False,
    ) -> Operator:
        # A trailing semicolon or blank changes nothing, so it must not change the identity.
        sql = sql.strip().rstrip(";").strip()
        if not sql:
            raise Invalid("A transform needs SQL")
        inputs = tuple(inputs)
        params = TransformParams(sql=sql).model_dump(mode="json")
        id = operator_identity(project_id, OperatorKind.TRANSFORM, params, inputs)
        if existing := await self._find(id):
            return existing
        columns = await self.describe(project_id, sql, inputs)
        declared = roles is not None and roles != Roles()
        if roles is not None:
            check_roles(roles, columns)
            # Bounds do not survive an aggregation (schema/intervals.py).
            await check_bounds(self.store, sql, roles)
        operator = Operator(
            id=id,
            project_id=project_id,
            kind=OperatorKind.TRANSFORM,
            params=params,
            inputs=inputs,
            # The columns are certain; what they mean after arbitrary SQL is not, so roles
            # come only from the caller.
            output=Schema(columns=columns, roles=roles or Roles(), derived=not declared),
            materializing=materialize,
            created_by=actor,
            created_at=self.clock.now(),
        )
        return await self.operators.add(operator)

    async def add_input(
        self, project_id: Id, name: str, output: Schema, default: OperatorId, actor: Actor
    ) -> Operator:
        if not name.strip():
            raise Invalid("An input needs a name")
        if output.kind is not OutputKind.TABLE or not output.columns:
            raise Invalid("An input declares the columns of the table it takes")
        params = InputParams(name=name).model_dump(mode="json")
        # The default is the input's upstream, so the lineage shows what it reads unless a
        # run binds it to something else.
        id = operator_identity(project_id, OperatorKind.INPUT, params, (default,))
        if existing := await self._find(id):
            return existing
        check_unique(output.columns)
        check_roles(output.roles, output.columns)
        fallback = await self._upstream(project_id, default)
        check_fits(output, await self.columns.of(fallback), f"The default {default}")
        check_compatible(output.roles, fallback.output.roles, f"The default {default}")
        operator = Operator(
            id=id,
            project_id=project_id,
            kind=OperatorKind.INPUT,
            params=params,
            inputs=(default,),
            output=output.model_copy(update={"derived": False}),
            materializing=False,
            created_by=actor,
            created_at=self.clock.now(),
        )
        return await self.operators.add(operator)

    async def get(self, id: OperatorId) -> Operator:
        return await self.operators.get(id)

    async def lineage(self, id: OperatorId) -> Sequence[Operator]:
        return await self.operators.upstream(id)

    async def pipelines(self, project_id: Id) -> Sequence[Pipeline]:
        operators = await self.operators.list(project_id)
        names = {source.id: source.name for source in await self.data_sources.list(project_id)}
        return listing.pipelines(operators, names)

    async def _find(self, id: OperatorId) -> Operator | None:
        try:
            return await self.operators.get(id)
        except NotFound:
            return None

    async def _upstream(self, project_id: Id, id: OperatorId) -> Operator:
        try:
            operator = await self.operators.get(id)
        except NotFound:
            raise Invalid(f"Operator {id} does not exist") from None
        if operator.project_id != project_id:
            raise Invalid(f"Operator {id} belongs to another project")
        if operator.output.kind is not OutputKind.TABLE:
            raise Invalid(f"Operator {id} does not produce a table")
        return operator
