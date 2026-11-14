"""Stand-ins for outbound ports that need the outside world. The repositories, the event
bus and the task dispatcher have in-memory implementations in ada.adapters.memory; use
those directly."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from ada.core.models.analysis import FetchedData, Query, Rows, StoredSnapshot
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, Schema
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.models.web import Monitor, PageText, SearchHit, SearchScope
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.sources import SourceReader, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import PageReader, WebSearch


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


RECORDINGS = Path(__file__).parent / "recordings"


class Replay:
    """An HTTP handler (for httpx.MockTransport) that answers the requests recorded in
    tests/recordings and fails every other one, so a test can never reach the network."""

    def __init__(self) -> None:
        index = json.loads((RECORDINGS / "sources.json").read_text())
        self.exchanges: list[dict[str, Any]] = index["exchanges"]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for exchange in self.exchanges:
            if exchange["method"] == request.method and _same(exchange["url"], request.url):
                if "request" in exchange:
                    expected = json.loads((RECORDINGS / exchange["request"]).read_bytes())
                    assert json.loads(request.content) == expected
                return httpx.Response(
                    exchange["status"],
                    headers={"Content-Type": exchange["content_type"]},
                    content=(RECORDINGS / exchange["body"]).read_bytes(),
                )
        raise AssertionError(f"No recording for {request.method} {request.url}")


def _same(recorded: str, url: httpx.URL) -> bool:
    expected = httpx.URL(recorded)
    return (expected.host, expected.path, sorted(expected.params.multi_items())) == (
        url.host,
        url.path,
        sorted(url.params.multi_items()),
    )


class WebReplay:
    """An HTTP handler for the web tools: answers the exchanges of tests/recordings/web.json
    and fails every other request. Two exchanges share POST /web/scrape, so the recorded
    request body picks the answer. The "name" of a monitor is our label, not compared."""

    def __init__(self) -> None:
        index = json.loads((RECORDINGS / "web.json").read_text())
        self.exchanges: list[dict[str, Any]] = index["exchanges"]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content) if request.content else None
        for exchange in self.exchanges:
            if exchange["method"] != request.method or not _same(exchange["url"], request.url):
                continue
            if "request" in exchange:
                expected = json.loads((RECORDINGS / exchange["request"]).read_bytes())
                if _without_name(body) != _without_name(expected):
                    continue
            return httpx.Response(
                exchange["status"],
                headers={"Content-Type": exchange["content_type"]},
                content=(RECORDINGS / exchange["body"]).read_bytes(),
            )
        raise AssertionError(f"No recording for {request.method} {request.url}: {body}")


def _without_name(body: Any) -> Any:
    return {k: v for k, v in body.items() if k != "name"} if isinstance(body, dict) else body


class FakeWebSearch(WebSearch):
    """Returns the given hits and pages; records every search."""

    def __init__(self, hits: Sequence[SearchHit] = (), pages: Sequence[PageText] = ()) -> None:
        self.hits = hits
        self.pages = pages
        self.searches: list[tuple[str, SearchScope, int]] = []
        self.fetched: list[Sequence[str]] = []

    async def search(self, query: str, scope: SearchScope, limit: int) -> Sequence[SearchHit]:
        self.searches.append((query, scope, limit))
        return self.hits[:limit]

    async def contents(self, urls: Sequence[str]) -> Sequence[PageText]:
        self.fetched.append(urls)
        return [page for page in self.pages if page.url in urls]


class FakePageReader(PageReader):
    """Returns canned text, rows and monitors; records every call."""

    def __init__(
        self, text: str = "", rows: Sequence[JsonObject] = (), secret: str = "test-secret"
    ) -> None:
        self.text = text
        self.rows = list(rows)
        self.secret = secret
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def read(self, url: str) -> PageText:
        self.calls.append(("read", (url,)))
        return PageText(url=url, text=self.text)

    async def extract(self, url: str, instruction: str, columns: Sequence[str]) -> list[JsonObject]:
        self.calls.append(("extract", (url, instruction, tuple(columns))))
        return self.rows

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        self.calls.append(("watch", (url, webhook_url)))
        return Monitor(id=f"mon_{len(self.calls)}", secret=SecretStr(self.secret))

    async def unwatch(self, monitor_id: str) -> None:
        self.calls.append(("unwatch", (monitor_id,)))
