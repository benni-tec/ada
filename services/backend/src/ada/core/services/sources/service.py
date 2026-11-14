from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.operators import Operator, OperatorId, OperatorKind, operator_identity
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
    RefreshResult,
)
from ada.core.models.time import TimeRange
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    SnapshotRepository,
)
from ada.core.ports.sources import SourceCheckLog, SourceReader, SourceReaders
from ada.core.ports.system import Clock
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.freshness import check_policy, is_due, wants_check
from ada.core.services.sources.shaping import shape, shape_options

# Refreshes and source operators are platform work, whoever triggered them.
PLATFORM = Actor(kind=ActorKind.SYSTEM, name="ada")

# Wave 1 fetches each source whole, so all its snapshots share one key. Fetching by period
# will key them by the period instead.
WHOLE_SOURCE = ""


def source_operator_id(source: DataSource) -> OperatorId:
    """The id of the one source operator that reads this data source. The pipeline service
    computes the same identity when an agent adds a source to a pipeline."""
    params = {"data_source_id": str(source.id)}
    return operator_identity(source.project_id, OperatorKind.SOURCE, params, ())


class DataSources(SourceService):
    """Registers data sources and keeps their snapshots fresh. Snapshots of a source are
    written here only, under its source operator, so a run that refreshes a source and
    then reads it finds the snapshot where it expects it."""

    def __init__(
        self,
        projects: ProjectRepository,
        sources: DataSourceRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        readers: SourceReaders,
        checks: SourceCheckLog,
        store: AnalysisStore,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.projects = projects
        self.sources = sources
        self.operators = operators
        self.snapshots = snapshots
        self.readers = readers
        self.checks = checks
        self.store = store
        self.events = events
        self.clock = clock

    async def register(
        self,
        project_id: Id,
        name: str,
        access_kind: AccessKind,
        address: str,
        format: DataFormat,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        await self.projects.get(project_id)
        # Fails now for a kind nobody can read yet, instead of at the first refresh.
        self.readers.for_kind(access_kind)
        now = self.clock.now()
        source = DataSource(
            id=uuid7(),
            project_id=project_id,
            name=name.strip(),
            access_kind=access_kind,
            address=address.strip(),
            format=format,
            options=options or {},
            freshness=freshness or FreshnessPolicy(),
            declared_schema=declared_schema,
            created_at=now,
        )
        _check(source)
        await self.sources.add(source)
        # The source operator exists from the start, so a widget's lineage always ends at
        # a source with its address, and the snapshots have an operator to belong to.
        await self.operators.add(
            Operator(
                id=source_operator_id(source),
                project_id=project_id,
                kind=OperatorKind.SOURCE,
                params={"data_source_id": str(source.id)},
                inputs=(),
                output=declared_schema or Schema(),
                materializing=True,
                created_by=PLATFORM,
                created_at=now,
            )
        )
        return source

    async def get(self, id: Id) -> DataSource:
        return await self.sources.get(id)

    async def list(self, project_id: Id) -> Sequence[DataSource]:
        await self.projects.get(project_id)
        return await self.sources.list(project_id)

    async def update(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        address: str | None = None,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        # A changed address or options is read by the next refresh that fetches; the
        # caller forces one to read it at once. The source operator keeps its declared
        # output, since operators never change.
        source = await self.sources.get(id)
        changes = {
            "name": name.strip() if name is not None else None,
            "address": address.strip() if address is not None else None,
            "options": options,
            "freshness": freshness,
            "declared_schema": declared_schema,
        }
        updated = source.model_copy(update={k: v for k, v in changes.items() if v is not None})
        _check(updated)
        return await self.sources.update(updated, expected_revision)

    async def refresh(self, id: Id, force: bool = False) -> RefreshResult:
        source = await self.sources.get(id)
        operator_id = source_operator_id(source)
        current = await self.snapshots.current(operator_id, WHOLE_SOURCE)
        now = self.clock.now()
        if not force and not wants_check(source, current, now):
            # The common case when a run starts: nothing to do, and nothing is fetched.
            return RefreshResult(data_source_id=source.id, changed=False)

        token = source.last_probe_token
        try:
            reader = self.readers.for_kind(source.access_kind)
            if not force and source.freshness.kind is FreshnessKind.PROBE:
                probed = await reader.probe(source)
                if current is not None and probed is not None and probed == token:
                    await self.sources.record_check(source.id, now, token, None)
                    await self._publish(source, EventType.SOURCE_REFRESHED, changed=False)
                    return RefreshResult(data_source_id=source.id, changed=False)
                # Stored only after the fetch succeeds, so a failed fetch is retried even
                # though the probe already saw the new token.
                token = probed
            snapshot = await self._fetch(reader, source, operator_id, current)
        except Exception as error:
            message = str(error) or type(error).__name__
            # Recorded apart from the caller's transaction: the error is raised on, and a
            # caller that fails with it (a run whose source has no data yet) rolls back.
            # A success is recorded in the caller's transaction, with the snapshot it
            # wrote, so the token never says "fetched" without the data to show for it.
            await self.checks.record_failure(source.id, now, source.last_probe_token, message)
            # Goes out with the caller's transaction, like every event: a caller that
            # handles the error (the worker) announces it; one that fails does not.
            await self._publish(
                source, EventType.SOURCE_REFRESH_FAILED, changed=False, error=message
            )
            raise

        await self.sources.record_check(source.id, now, token, None)
        await self._publish(source, EventType.SOURCE_REFRESHED, changed=snapshot is not None)
        return RefreshResult(
            data_source_id=source.id,
            changed=snapshot is not None,
            snapshot_ids=(snapshot.id,) if snapshot else (),
        )

    async def due(self) -> Sequence[DataSource]:
        now = self.clock.now()
        due: list[DataSource] = []
        for source in await self.sources.list_all():
            current = await self.snapshots.current(source_operator_id(source), WHOLE_SOURCE)
            if is_due(source, current, now):
                due.append(source)
        return due

    async def _fetch(
        self,
        reader: SourceReader,
        source: DataSource,
        operator_id: OperatorId,
        current: Snapshot | None,
    ) -> Snapshot | None:
        """Fetch and store the source. Returns the new snapshot, or None when the content
        is the same as the current snapshot's."""
        fetched = await reader.fetch(source, TimeRange())
        stored = await self.store.write(
            source.project_id, shape(fetched, source.options), source.declared_schema
        )
        if current is not None and current.content_hash == stored.content_hash:
            # Same hash, same downstream identities: nothing after this needs to run again.
            return None
        snapshot = Snapshot(
            id=uuid7(),
            project_id=source.project_id,
            operator_id=operator_id,
            parameters_key=WHOLE_SOURCE,
            content_hash=stored.content_hash,
            location=stored.location,
            row_count=stored.row_count,
            fetched_at=fetched.fetched_at,
        )
        await self.snapshots.add(snapshot)
        if current is not None:
            await self.snapshots.supersede(current.id, self.clock.now())
        return snapshot

    async def _publish(
        self, source: DataSource, type: EventType, changed: bool, error: str | None = None
    ) -> None:
        payload: JsonObject = {"data_source_id": str(source.id), "changed": changed}
        if error is not None:
            payload["error"] = error
        await self.events.publish(
            Event(type=type, project_id=source.project_id, payload=payload, at=self.clock.now())
        )


def _check(source: DataSource) -> None:
    """Raises Invalid for a registration that cannot work."""
    if not source.name:
        raise Invalid("A data source needs a name")
    if not source.address:
        raise Invalid("A data source needs an address")
    check_policy(source.freshness)
    shape_options(source.options)
