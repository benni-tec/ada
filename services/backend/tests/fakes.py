"""Stand-ins for outbound ports that need the outside world. The repositories, the event
bus and the task dispatcher have in-memory implementations in ada.adapters.memory; use
those directly."""

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from ada.core.models.agents import ModelTarget
from ada.core.models.analysis import FetchedData, Query, Rows, StoredSnapshot
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.judges import Finding, JudgeContext
from ada.core.models.schema import Column, Schema
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.models.web import (
    Answer,
    Crawl,
    Extraction,
    Monitor,
    PdfOptions,
    SearchHit,
    SearchResults,
    SearchScope,
    WebLink,
    WebPage,
)
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.judges import JudgeModel
from ada.core.ports.sources import SourceReader, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebExplorer, WebSearch


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
        # What fetches report as their origin; the source address when None.
        self.origin: str | None = None

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        self.fetches.append((source.id, time_range))
        if isinstance(self.content, Exception):
            raise self.content
        return FetchedData(
            content=self.content,
            format=self.format,
            fetched_at=self.clock.now(),
            origin=self.origin or source.address,
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
    request body picks the answer. The "name" of a monitor and Context.dev's "tags" are our
    labels, not compared (the recordings were made without tags)."""

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
    if not isinstance(body, dict):
        return body
    return {k: v for k, v in body.items() if k not in ("name", "tags")}


class FakeWebSearch(WebSearch):
    """Returns the given hits, charging `credits` (None: like Exa, nothing stated); records
    every search and its tags."""

    def __init__(
        self, hits: Sequence[SearchHit] = (), configured: bool = True, credits: int | None = None
    ) -> None:
        self.hits = list(hits)
        self._configured = configured
        self.credits = credits
        self.searches: list[tuple[str, SearchScope, int]] = []
        self.tags: list[tuple[str, ...]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def search(
        self, query: str, scope: SearchScope, limit: int, *, tags: Sequence[str]
    ) -> SearchResults:
        self.searches.append((query, scope, limit))
        self.tags.append(tuple(tags))
        return SearchResults(hits=self.hits[:limit], credits=self.credits)


# The page FakeExplorer reads: a heading, a sentence and a table; a focused read returns
# the table alone.
PAGE_TABLE = """| County | Coverage |
| --- | --- |
| Uusimaa | 71 |
| Lappi | 64 |
"""
PAGE_MARKDOWN = f"""# Screening in Finland

Coverage by county:

{PAGE_TABLE}"""


class FakeExplorer(WebExplorer):
    """Context.dev: answers every call with what it is given and remembers the calls."""

    def __init__(
        self,
        configured: bool = True,
        rows: Sequence[JsonObject] = (),
        secret: str = "test-secret",
    ) -> None:
        self._configured = configured
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.failure: Exception | None = None
        self.page = WebPage(
            url="https://example.test/screening", title="Screening", markdown=PAGE_MARKDOWN
        )
        self.extraction = Extraction(rows=list(rows), credits=5)
        self.crawled = Crawl(
            pages=[
                WebPage(url="https://example.test/a", markdown="Page A"),
                WebPage(url="https://example.test/b", markdown=PAGE_MARKDOWN),
            ],
            credits=2,
        )
        self.answered = Answer(
            content={
                "rows": [
                    {"country": "FI", "rate": "71.5", "year": 2024},
                    {"country": "SE", "rate": 68, "year": "n/a"},
                ]
            },
            sources=["https://example.test/report"],
            credits=10,
        )
        self.secret = secret
        self.monitors = 0

    @property
    def configured(self) -> bool:
        return self._configured

    def _called(self, name: str, **arguments: Any) -> None:
        self.calls.append((name, arguments))
        if self.failure is not None:
            raise self.failure

    async def read(
        self,
        url: str,
        *,
        tags: Sequence[str],
        main_content_only: bool = False,
        focus: str | None = None,
        pdf: PdfOptions | None = None,
    ) -> WebPage:
        # Focus and PDF options are noted only when given.
        given = {k: v for k, v in {"focus": focus, "pdf": pdf}.items() if v is not None}
        self._called("read", url=url, tags=tags, **given)
        if focus:
            # The passages of the page relevant to the focus: its table.
            return self.page.model_copy(update={"markdown": PAGE_TABLE})
        return self.page

    async def extract(
        self,
        url: str,
        instruction: str,
        columns: Sequence[str],
        *,
        tags: Sequence[str],
        pdf: PdfOptions | None = None,
    ) -> Extraction:
        given = {"pdf": pdf} if pdf is not None else {}
        self._called(
            "extract",
            url=url,
            instruction=instruction,
            columns=list(columns),
            tags=tags,
            **given,
        )
        return self.extraction

    async def map(self, domain: str, **arguments: Any) -> list[WebLink]:
        self._called("map", domain=domain, **arguments)
        return [WebLink(url=f"https://{domain}/data", title="Data")]

    async def crawl(self, url: str, **arguments: Any) -> Crawl:
        self._called("crawl", url=url, **arguments)
        return self.crawled

    async def answer(self, task: str, json_format: dict[str, Any], **arguments: Any) -> Answer:
        self._called("answer", task=task, json_format=json_format, **arguments)
        return self.answered

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        self._called("watch", url=url, webhook_url=webhook_url)
        self.monitors += 1
        return Monitor(id=f"mon_{self.monitors}", secret=SecretStr(self.secret))

    async def unwatch(self, monitor_id: str) -> None:
        self._called("unwatch", monitor_id=monitor_id)


def context_signature(secret: str, body: bytes, at: int) -> str:
    """The x-context-signature header Context.dev sends for a delivery made at unix time `at`."""
    digest = hmac.new(secret.encode(), f"{at}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


# Outside a resolved placeholder (⟦...⟧): a number with digits, a figure the text typed.
_TYPED = re.compile(r"⟦[^⟧]*⟧|(\d[\d,.]*\s*%?)")
# A literal array of three or more numbers in code.
_ARRAY = re.compile(r"\[\s*-?\d[\d.]*(\s*,\s*-?\d[\d.]*){2,}\s*\]")


@dataclass
class JudgeCall:
    model: ModelTarget
    system: str
    content: str
    context: JudgeContext


class FakeJudgeModel(JudgeModel):
    """A judge that applies a crude rule of its kind: a text widget fails for a number typed
    outside a resolved placeholder, widget code for a literal array of numbers. Set
    `failure` to make the call fail. Records every call."""

    def __init__(self) -> None:
        self.calls: list[JudgeCall] = []
        self.failure: Exception | None = None

    async def decide(
        self, model: ModelTarget, system: str, content: str, context: JudgeContext
    ) -> tuple[Finding, ...]:
        self.calls.append(JudgeCall(model, system, content, context))
        if self.failure is not None:
            raise self.failure
        if "text widgets" in system:
            typed = [m.group(1) for m in _TYPED.finditer(content) if m.group(1)]
            return tuple(
                Finding(message="Use a placeholder for this figure", excerpt=figure.strip())
                for figure in typed
            )
        return tuple(
            Finding(message="Data comes from the inputs", excerpt=m.group(0))
            for m in _ARRAY.finditer(content)
        )
