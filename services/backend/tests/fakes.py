"""Stand-ins for outbound ports that need the outside world. The repositories, the event
bus and the task dispatcher have in-memory implementations in ada.adapters.memory; use
those directly."""

from datetime import UTC, datetime, timedelta

from ada.core.models.analysis import FetchedData, Query, Rows, StoredSnapshot
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, Schema
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.sources import SourceReader, SourceReaders
from ada.core.ports.system import Clock


class FixedClock(Clock):
    """A clock that only moves when told to."""

    def __init__(self, at: datetime | None = None) -> None:
        self.at = at or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)


class FakeSourceReader(SourceReader):
    """Returns `content` for every fetch and `token` for every probe; set either to an
    exception to make the call fail. Counts its calls."""

    def __init__(self, content: bytes = b"", format: DataFormat = DataFormat.CSV) -> None:
        self.content: bytes | Exception = content
        self.format = format
        self.token: str | None | Exception = None
        self.fetches: list[tuple[Id, TimeRange]] = []
        self.probes: list[Id] = []
        self.clock: Clock = FixedClock()

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        self.fetches.append((source.id, time_range))
        if isinstance(self.content, Exception):
            raise self.content
        return FetchedData(
            content=self.content,
            format=self.format,
            fetched_at=self.clock.now(),
            origin=source.address,
        )

    async def probe(self, source: DataSource) -> str | None:
        self.probes.append(source.id)
        if isinstance(self.token, Exception):
            raise self.token
        return self.token


class FakeSourceReaders(SourceReaders):
    def __init__(self, readers: dict[AccessKind, SourceReader] | None = None) -> None:
        self.readers = readers or {}

    def for_kind(self, kind: AccessKind) -> SourceReader:
        try:
            return self.readers[kind]
        except KeyError:
            raise Invalid(f"No reader is installed for {kind.value} sources") from None


class FakeAnalysisStore(AnalysisStore):
    """Runs no SQL. `columns` and `rows` are what every describe and run returns; writes
    are remembered and given a hash of their content. For tests of what sits above the
    store; tests of queries themselves need the real one."""

    def __init__(self, columns: tuple[Column, ...] = (), rows: tuple[tuple[object, ...], ...] = ()):
        self.columns = columns
        self.rows = rows
        self.written: list[FetchedData] = []
        self.materialized: list[Query] = []
        self.queries: list[Query] = []

    async def is_usable(self) -> bool:
        return True

    async def write(
        self, project_id: Id, data: FetchedData, declared: Schema | None = None
    ) -> StoredSnapshot:
        self.written.append(data)
        content_hash = format(hash(data.content) & 0xFFFFFFFFFFFF, "x")
        return StoredSnapshot(
            location=f"memory://{project_id}/{content_hash}",
            content_hash=content_hash,
            row_count=len(self.rows),
            output=declared or Schema(columns=self.columns, derived=True),
        )

    async def materialize(self, project_id: Id, query: Query) -> StoredSnapshot:
        self.materialized.append(query)
        content_hash = format(hash(query.sql) & 0xFFFFFFFFFFFF, "x")
        return StoredSnapshot(
            location=f"memory://{project_id}/{content_hash}",
            content_hash=content_hash,
            row_count=len(self.rows),
            output=Schema(columns=self.columns, derived=True),
        )

    async def describe(self, query: Query) -> tuple[Column, ...]:
        return self.columns

    async def run(self, query: Query, limit: int) -> Rows:
        self.queries.append(query)
        return Rows(columns=self.columns, rows=self.rows[:limit], truncated=len(self.rows) > limit)
