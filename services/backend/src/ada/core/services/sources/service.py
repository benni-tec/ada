import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from uuid import uuid7

from ada.core.models.actors import PLATFORM
from ada.core.models.analysis import Query
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.operators import Operator, OperatorId, OperatorKind, operator_identity
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Schema, TimeRole
from ada.core.models.sources import (
    DOCUMENT_COLUMNS,
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
    RefreshResult,
    document_extract,
)
from ada.core.models.time import Interval, TimeRange
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    SnapshotRepository,
)
from ada.core.ports.sources import SourceCheckLog, SourceLocks, SourceReader, SourceReaders
from ada.core.ports.system import Clock
from ada.core.services.pipelines.fusion import stand_in_sql, union
from ada.core.services.pipelines.schemas import check_unique
from ada.core.services.ports.sources import SourceService
from ada.core.services.schema.roles import check_roles
from ada.core.services.schema.time import period_key, periods
from ada.core.services.sources.freshness import check_policy, is_due, wants_check
from ada.core.services.sources.pushdown import (
    PushdownOptions,
    check_pushdown,
    is_stale,
    pushdown_options,
    request,
    time_role,
)
from ada.core.services.sources.shaping import shape, shape_options, split_periods

# The key of the snapshot of the whole source, as `refresh` fetches it. A source that
# fetches by period (pushdown.py) also keeps one snapshot per period, keyed
# `period:<start>/<end>`, and unions of them for the ranges runs asked for, keyed
# `range:<digest of the periods and their contents>`.
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
        locks: SourceLocks,
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
        self.locks = locks

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
        if access_kind is AccessKind.DOCUMENT:
            declared_schema = _document_schema(options or {}, declared_schema)
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
        # Only now, so runs that fetch nothing never wait. Whoever held it may have just
        # fetched: read again and decide again.
        await self.locks.hold(source.id)
        source = await self.sources.get(id)
        current = await self.snapshots.current(operator_id, WHOLE_SOURCE)
        if not force and not wants_check(source, current, now):
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

        if force or (
            source.freshness.kind is FreshnessKind.PROBE and token != source.last_probe_token
        ):
            # A forced refresh follows an edit of the address or options, or a person who
            # knows better; a new probe token says the source changed. Either way the
            # periods stored before may be outdated: they are fetched again when asked for.
            await self._retire(operator_id, now)
        await self.sources.record_check(source.id, now, token, None)
        await self._publish(source, EventType.SOURCE_REFRESHED, changed=snapshot is not None)
        return RefreshResult(
            data_source_id=source.id,
            changed=snapshot is not None,
            snapshot_ids=(snapshot.id,) if snapshot else (),
        )

    async def refresh_range(self, id: Id, time_range: TimeRange) -> Snapshot | None:
        return await self._refresh_range(id, time_range, locked=False)

    async def _refresh_range(self, id: Id, time_range: TimeRange, locked: bool) -> Snapshot | None:
        source = await self.sources.get(id)
        pushdown = pushdown_options(source.options)
        role = time_role(source)
        if pushdown is None or role is None or role.grain is None or time_range.start is None:
            return None
        assert source.declared_schema is not None
        operator_id = source_operator_id(source)
        now = self.clock.now()
        wanted = periods(time_range, role.grain, now.date())
        stored: dict[Interval, Snapshot | None] = {
            period: await self.snapshots.current(operator_id, period_key(period))
            for period in wanted
        }
        newest = await self._newest_period(operator_id)
        if not locked and _wants_work(source, stored, newest, now):
            # Only when something is to be fetched or probed, so runs on fresh periods never
            # wait. Whoever held it may have stored these periods: read again.
            await self.locks.hold(source.id)
            return await self._refresh_range(id, time_range, locked=True)

        token = source.last_probe_token
        probed = changed_token = False
        written: dict[Interval, Snapshot] = {}
        changed = False
        try:
            reader = self.readers.for_kind(source.access_kind)
            present = [snapshot for snapshot in stored.values() if snapshot is not None]
            # As for the whole source: probed at most every ttl_seconds, and before a
            # first fetch too, so the token stored is the one the data was fetched under.
            if source.freshness.kind is FreshnessKind.PROBE and wants_check(
                source, present[0] if present else None, now
            ):
                token = await reader.probe(source)
                probed = True
                changed_token = token is None or token != source.last_probe_token
            fetch = [
                period
                for period, snapshot in stored.items()
                if changed_token
                or snapshot is None
                or is_stale(source, period, snapshot, newest, now)
            ]
            if fetch:
                written, changed = await self._fetch_periods(
                    reader, source, operator_id, pushdown, role, fetch, stored
                )
        except Exception as error:
            message = str(error) or type(error).__name__
            await self.checks.record_failure(source.id, now, source.last_probe_token, message)
            await self._publish(
                source, EventType.SOURCE_REFRESH_FAILED, changed=False, error=message
            )
            if any(snapshot is None for snapshot in stored.values()):
                # A period that was never stored has nothing to serve in its place.
                raise
            # Every period has a last good snapshot: serve those; the recorded error marks
            # the widgets stale.
            return await self._union(source, operator_id, role, list(stored.values()))

        stored.update(written)
        if changed_token:
            # Everything stored before the change may be outdated, not only these periods.
            keep = {snapshot.id for snapshot in written.values()}
            await self._retire(operator_id, now, keep=keep, whole=True)
        if written or probed:
            # A probe confirms every stored snapshot, so it counts as a check of the whole
            # source; fetching periods does not, or it would put off refreshing the rest.
            checked = now if probed else source.last_checked_at or now
            await self.sources.record_check(source.id, checked, token, None)
            await self._publish(source, EventType.SOURCE_REFRESHED, changed=changed)
        return await self._union(source, operator_id, role, list(stored.values()))

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
        # Superseded first: at most one snapshot per operator and key is current, and the
        # database checks that on every write.
        if current is not None:
            await self.snapshots.supersede(current.id, self.clock.now())
        await self.snapshots.add(snapshot)
        return snapshot

    async def _fetch_periods(
        self,
        reader: SourceReader,
        source: DataSource,
        operator_id: OperatorId,
        pushdown: PushdownOptions,
        role: TimeRole,
        fetch: list[Interval],
        stored: dict[Interval, Snapshot | None],
    ) -> tuple[dict[Interval, Snapshot], bool]:
        """Fetch these periods in one request and store each as a snapshot of its own.
        Returns the snapshots and whether any content differs from what was stored.

        A period fetched again gets a new snapshot even when its content is the same,
        pointing at the same stored file: its fetch time is how the period's age is
        measured, and identical content keeps every downstream identity anyway."""
        assert source.declared_schema is not None and role.grain is not None
        declared = source.declared_schema
        asked = request(source, pushdown, fetch, role.grain)
        fetched = await reader.fetch(asked, TimeRange(start=fetch[0].start, end=fetch[-1].end))
        parts = split_periods(shape(fetched, source.options), role, fetch)
        written: dict[Interval, Snapshot] = {}
        changed = False
        for period in fetch:
            if period in parts:
                data = await self.store.write(source.project_id, parts[period], declared)
            else:
                # Nothing for this period yet, e.g. a year not published: an empty table
                # with the declared columns, so the period counts as fetched.
                empty = Query(sql=stand_in_sql(declared.columns))
                data = await self.store.materialize(source.project_id, empty)
            previous = stored[period]
            changed = changed or previous is None or previous.content_hash != data.content_hash
            if previous is not None:
                await self.snapshots.supersede(previous.id, self.clock.now())
            snapshot = Snapshot(
                id=uuid7(),
                project_id=source.project_id,
                operator_id=operator_id,
                parameters_key=period_key(period),
                period=period,
                content_hash=data.content_hash,
                location=data.location,
                row_count=data.row_count,
                fetched_at=fetched.fetched_at,
            )
            await self.snapshots.add(snapshot)
            written[period] = snapshot
        return written, changed

    async def _union(
        self,
        source: DataSource,
        operator_id: OperatorId,
        role: TimeRole,
        parts: list[Snapshot | None],
    ) -> Snapshot:
        """The periods as one snapshot, which a run fixes for the source operator. Keyed
        by the periods and their contents, so the same periods with the same data are
        put together once."""
        assert source.declared_schema is not None
        columns = source.declared_schema.columns
        present = [part for part in parts if part is not None]
        key = "range:" + _digest([[part.parameters_key, part.content_hash] for part in present])
        if existing := await self.snapshots.current(operator_id, key):
            return existing
        # Two runs on the same fresh periods would both put the union together; the second
        # finds the first's once it holds the source. Taking the lock again is harmless.
        await self.locks.hold(source.id)
        if existing := await self.snapshots.current(operator_id, key):
            return existing
        query = union(columns, present, role.start) if present else Query(sql=stand_in_sql(columns))
        data = await self.store.materialize(source.project_id, query)
        snapshot = Snapshot(
            id=uuid7(),
            project_id=source.project_id,
            operator_id=operator_id,
            parameters_key=key,
            content_hash=data.content_hash,
            location=data.location,
            row_count=data.row_count,
            # As old as its oldest part: that is what it can vouch for.
            fetched_at=min((part.fetched_at for part in present), default=self.clock.now()),
        )
        await self.snapshots.add(snapshot)
        return snapshot

    async def _newest_period(self, operator_id: OperatorId) -> date | None:
        """Where the newest periods begin: the start of the latest stored period with rows.
        Periods from there on are the ones a source still revises or has yet to fill."""
        starts = [
            snapshot.period.start
            for snapshot in await self.snapshots.list(operator_id)
            if snapshot.superseded_at is None and snapshot.period and snapshot.row_count
        ]
        return max(starts, default=None)

    async def _retire(
        self, operator_id: OperatorId, at: datetime, keep: set[Id] | None = None, whole=False
    ) -> None:
        """Supersede the source's stored periods and their unions, except `keep`, and with
        `whole` the whole-source snapshot too. Runs that fixed them keep reading them; the
        next run that asks fetches again."""
        for snapshot in await self.snapshots.list(operator_id):
            if snapshot.superseded_at is not None or (keep and snapshot.id in keep):
                continue
            if snapshot.parameters_key == WHOLE_SOURCE and not whole:
                continue
            await self.snapshots.supersede(snapshot.id, at)

    async def _publish(
        self, source: DataSource, type: EventType, changed: bool, error: str | None = None
    ) -> None:
        payload: JsonObject = {"data_source_id": str(source.id), "changed": changed}
        if error is not None:
            payload["error"] = error
        await self.events.publish(
            Event(type=type, project_id=source.project_id, payload=payload, at=self.clock.now())
        )


def _wants_work(
    source: DataSource,
    stored: dict[Interval, Snapshot | None],
    newest: date | None,
    now: datetime,
) -> bool:
    """Whether refreshing these periods would probe or fetch anything."""
    present = [snapshot for snapshot in stored.values() if snapshot is not None]
    if source.freshness.kind is FreshnessKind.PROBE and wants_check(
        source, present[0] if present else None, now
    ):
        return True
    return any(
        snapshot is None or is_stale(source, period, snapshot, newest, now)
        for period, snapshot in stored.items()
    )


def _check(source: DataSource) -> None:
    """Raises Invalid for a registration that cannot work."""
    if not source.name:
        raise Invalid("A data source needs a name")
    if not source.address:
        raise Invalid("A data source needs an address")
    check_policy(source.freshness)
    shape_options(source.options)
    _check_document(source)
    declared = source.declared_schema
    if declared is not None and declared.columns:
        check_unique(declared.columns)
        check_roles(declared.roles, declared.columns)
    check_pushdown(source)


def _document_schema(options: JsonObject, declared: Schema | None) -> Schema:
    """A document source's declared schema: the extract mode's fixed columns, with the
    roles and kind the registration declared, if any. Columns it declares itself are kept
    for `_check_document` to compare."""
    columns = DOCUMENT_COLUMNS[document_extract(options)]
    if declared is None:
        return Schema(columns=columns)
    if not declared.columns:
        return declared.model_copy(update={"columns": columns})
    return declared


def _check_document(source: DataSource) -> None:
    """A PDF is read by document sources only, and a document source's columns are those
    of its extract mode, which therefore cannot change after registration."""
    is_document = source.access_kind is AccessKind.DOCUMENT
    if is_document != (source.format is DataFormat.PDF):
        raise Invalid('A document source has the format "pdf", and only a document source has')
    if not is_document:
        return
    extract = document_extract(source.options)
    expected = [column.name for column in DOCUMENT_COLUMNS[extract]]
    declared = source.declared_schema
    if declared is None or [column.name for column in declared.columns] != expected:
        raise Invalid(
            f'A document source with extract "{extract.value}" has the columns '
            f"{', '.join(expected)}; to extract something else, register another source"
        )


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]
