"""The web on ADA's account: the web tools over MCP, web sources, the credit budget and
the Context.dev client. Context.dev is faked (FakeExplorer, or httpx's MockTransport)."""

import json
import tempfile
from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
from dishka import Provider, Scope, provide
from fastmcp import Client
from fastmcp.exceptions import ToolError

import factories
from ada.adapters.db.web_repositories import SqlWebBudget
from ada.adapters.memory.repositories import MemoryStore
from ada.adapters.memory.web import MemoryWebBudget
from ada.adapters.sources.web import WebPageReader
from ada.adapters.web.context_dev import ContextDevWeb
from ada.config import Settings
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
)
from ada.core.models.time import TimeRange
from ada.core.ports.web import (
    Answer,
    Crawl,
    SearchResult,
    WebExplorer,
    WebLink,
    WebPage,
)
from ada.core.services.ports.web import EXPLORATION_NOTE
from api_support import Seen, call, mcp_client
from db_helpers import engine_for, unit_of_work
from fakes import FakeAnalysisStore, FakeSourceReaders, FixedClock
from test_sources import data_sources

pytestmark = pytest.mark.anyio

DAY = 24 * 60 * 60
PAGE = """# Screening in Finland

Coverage by county:

| County | Coverage |
| --- | --- |
| Uusimaa | 71 |
| Lappi | 64 |
"""


class FakeExplorer(WebExplorer):
    """Answers every call with what it is given and remembers the calls."""

    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.page = WebPage(url="https://example.test/screening", title="Screening", markdown=PAGE)
        self.failure: Exception | None = None
        self.crawled = Crawl(
            pages=[
                WebPage(url="https://example.test/a", markdown="Page A"),
                WebPage(url="https://example.test/b", markdown=PAGE),
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

    @property
    def configured(self) -> bool:
        return self._configured

    def _called(self, name: str, **arguments: Any) -> None:
        self.calls.append((name, arguments))
        if self.failure is not None:
            raise self.failure

    async def search(self, query: str, **arguments: Any) -> list[SearchResult]:
        self._called("search", query=query, **arguments)
        return [SearchResult(title="THL", url="https://thl.fi/stats", snippet="Statistics")]

    async def read(self, url: str, *, tags: Sequence[str]) -> WebPage:
        self._called("read", url=url, tags=tags)
        return self.page

    async def map(self, domain: str, **arguments: Any) -> list[WebLink]:
        self._called("map", domain=domain, **arguments)
        return [WebLink(url=f"https://{domain}/data", title="Data")]

    async def crawl(self, url: str, **arguments: Any) -> Crawl:
        self._called("crawl", url=url, **arguments)
        return self.crawled

    async def answer(self, task: str, json_format: dict[str, Any], **arguments: Any) -> Answer:
        self._called("answer", task=task, json_format=json_format, **arguments)
        return self.answered


class FakeWeb(Provider):
    def __init__(self, explorer: FakeExplorer) -> None:
        super().__init__()
        self.explorer = explorer

    @provide(scope=Scope.APP)
    def explorer_(self) -> WebExplorer:
        return self.explorer


# The web tools


@pytest.fixture(scope="module")
async def web(unreachable_settings: Settings) -> AsyncIterator[tuple[Client, Seen, FakeExplorer]]:
    explorer = FakeExplorer()
    settings = unreachable_settings.model_copy(update={"web_daily_credit_limit": 4})
    async with mcp_client(settings, FakeWeb(explorer)) as (client, seen):
        yield client, seen, explorer


async def _project_and_session(client: Client) -> tuple[str, str]:
    project = await call(client, "create_project", name="Web")
    session = await call(client, "create_session", project_id=project["id"], title="Look")
    return project["id"], session["id"]


async def test_the_web_tools_answer_with_the_note_and_tag_the_project(
    web: tuple[Client, Seen, FakeExplorer],
) -> None:
    client, _, explorer = web
    project_id, session_id = await _project_and_session(client)
    explorer.calls.clear()

    found = await call(
        client,
        "web_search",
        project_id=project_id,
        session_id=session_id,
        query="cancer screening coverage",
        num_results=5,
        country="fi",
    )
    read = await call(
        client,
        "web_read",
        project_id=project_id,
        session_id=session_id,
        url="https://example.test/screening",
        max_chars=20,
    )
    mapped = await call(
        client, "web_map", project_id=project_id, session_id=session_id, domain="thl.fi"
    )

    assert found["results"] == [
        {"title": "THL", "url": "https://thl.fi/stats", "snippet": "Statistics"}
    ]
    assert read["markdown"] == PAGE[:20] and read["truncated"] is True
    assert read["title"] == "Screening"
    assert mapped["links"] == [{"url": "https://thl.fi/data", "title": "Data"}]
    assert {found["note"], read["note"], mapped["note"]} == {EXPLORATION_NOTE}
    tags = ("ada", f"project:{project_id}")
    assert explorer.calls == [
        (
            "search",
            {
                "query": "cancer screening coverage",
                "num_results": 5,
                "include_domains": None,
                "exclude_domains": None,
                "country": "fi",
                "languages": None,
                "tags": tags,
            },
        ),
        ("read", {"url": "https://example.test/screening", "tags": tags}),
        ("map", {"domain": "thl.fi", "search": None, "max_links": 50, "tags": tags}),
    ]
    tools = {tool.name: tool for tool in await client.list_tools()}
    for name in ("web_search", "web_read", "web_map"):
        assert "never show or quote" in (tools[name].description or ""), name
        assert {"project_id", "session_id"} <= set(tools[name].input_schema["required"]), name


async def test_the_web_budget_of_a_project_refuses_once_its_credits_are_spent(
    web: tuple[Client, Seen, FakeExplorer],
) -> None:
    client, _, explorer = web
    project_id, session_id = await _project_and_session(client)
    other_project, other_session = await _project_and_session(client)
    explorer.calls.clear()
    ids = {"project_id": project_id, "session_id": session_id}

    # Twenty results are two credits, a read and a map one each: the limit is four.
    await call(client, "web_search", **ids, query="screening", num_results=20)
    await call(client, "web_read", **ids, url="https://example.test/a")
    await call(client, "web_map", **ids, domain="thl.fi")
    with pytest.raises(ToolError, match=r"web budget of this project \(4 credits a day\)"):
        await call(client, "web_read", **ids, url="https://example.test/b")

    # Nothing was sent for the refused call; another project has its own budget.
    assert len(explorer.calls) == 3
    await call(
        client,
        "web_read",
        project_id=other_project,
        session_id=other_session,
        url="https://example.test/b",
    )


async def test_a_web_tool_takes_a_session_of_its_own_project_only(
    web: tuple[Client, Seen, FakeExplorer],
) -> None:
    client, _, explorer = web
    project_id, _ = await _project_and_session(client)
    _, foreign_session = await _project_and_session(client)
    explorer.calls.clear()

    with pytest.raises(ToolError, match="is not in project"):
        await call(
            client, "web_map", project_id=project_id, session_id=foreign_session, domain="thl.fi"
        )
    assert explorer.calls == []


# Web sources


def _web_source(**changes: Any) -> DataSource:
    options = changes.pop("options", {})
    return factories.data_source(
        factories.project().id,
        name="Screening page",
        access_kind=AccessKind.WEB,
        address="https://example.test/screening",
        format=DataFormat.HTML,
        options=options,
        **changes,
    )


def _rows(content: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rows.parquet"
        path.write_bytes(content)
        with duckdb.connect() as connection:
            relation = connection.sql(f"SELECT * FROM read_parquet('{path}')")
            return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def _reader(explorer: FakeExplorer, limit: int = 300) -> tuple[WebPageReader, MemoryWebBudget]:
    budget = MemoryWebBudget()
    return WebPageReader(explorer, budget, FixedClock(), limit), budget


async def test_a_web_page_is_read_as_pages_or_as_the_rows_of_its_tables() -> None:
    explorer = FakeExplorer()
    reader, budget = _reader(explorer)

    pages = await reader.fetch(_web_source(), TimeRange())
    tables = await reader.fetch(_web_source(options={"extract": "tables"}), TimeRange())

    assert pages.format is DataFormat.PARQUET
    assert _rows(pages.content) == [{"page": 1, "text": PAGE.strip()}]
    assert _rows(tables.content) == [
        {"page": 1, "table": 1, "row": 1, "cells": ["County", "Coverage"]},
        {"page": 1, "table": 1, "row": 2, "cells": ["Uusimaa", "71"]},
        {"page": 1, "table": 1, "row": 3, "cells": ["Lappi", "64"]},
    ]
    assert sum(budget.spent.values()) == 2


async def test_a_crawl_is_a_page_per_row_and_an_answer_its_records_with_their_sources() -> None:
    explorer = FakeExplorer()
    reader, budget = _reader(explorer)
    crawl = _web_source(options={"operation": "crawl", "max_pages": 5})
    columns = (
        Column(name="country", type=ColumnType.TEXT),
        Column(name="rate", type=ColumnType.NUMBER),
        Column(name="year", type=ColumnType.INTEGER),
        Column(name="sources", type=ColumnType.JSON),
    )
    answers = _web_source(
        options={
            "operation": "answers",
            "task": "Screening coverage per Nordic country",
            "json_format": {"rows": [{"country": "FI", "rate": 70.1, "year": 2024}]},
        },
        declared_schema=Schema(columns=columns),
    )

    crawled = _rows((await reader.fetch(crawl, TimeRange())).content)
    answered = _rows((await reader.fetch(answers, TimeRange())).content)

    assert crawled == [
        {"page": 1, "text": "https://example.test/a\n\nPage A"},
        {"page": 2, "text": f"https://example.test/b\n\n{PAGE.strip()}"},
    ]
    sources = ["https://example.test/report"]
    assert answered == [
        {"country": "FI", "rate": 71.5, "year": 2024, "sources": sources},
        {"country": "SE", "rate": 68.0, "year": None, "sources": sources},
    ]
    # Five credits reserved for the crawl, three given back; ten for the answer.
    assert sum(budget.spent.values()) == 2 + 10
    assert explorer.calls[0][1]["max_pages"] == 5


async def test_a_web_source_fails_readably_and_stays_counted() -> None:
    explorer = FakeExplorer()
    reader, budget = _reader(explorer, limit=1)
    explorer.failure = Invalid("Context.dev could not read https://example.test/screening: 404")

    source = _web_source()

    with pytest.raises(Invalid, match="could not read"):
        await reader.fetch(source, TimeRange())
    with pytest.raises(Invalid, match="does not leave the 1 this refresh"):
        await reader.fetch(source, TimeRange())
    unconfigured, _ = _reader(FakeExplorer(configured=False))
    with pytest.raises(Invalid, match="CONTEXT_DEV_API_KEY"):
        await unconfigured.fetch(_web_source(), TimeRange())
    assert sum(budget.spent.values()) == 1


async def test_web_sources_keep_their_minimum_freshness_and_refuse_early_forced_refreshes() -> None:
    memory = MemoryStore()
    clock = FixedClock()
    explorer = FakeExplorer()
    project = factories.project()
    memory.projects[project.id] = project
    reader = WebPageReader(explorer, MemoryWebBudget(), clock, 300)
    service, _ = data_sources(
        memory, FakeSourceReaders({AccessKind.WEB: reader}), FakeAnalysisStore(), clock
    )
    page = {
        "name": "Screening page",
        "access_kind": AccessKind.WEB,
        "address": "https://example.test/screening",
        "format": DataFormat.HTML,
    }

    hourly = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    with pytest.raises(Invalid, match="ttl of at least 1 days"):
        await service.register(project.id, **page, freshness=hourly)
    with pytest.raises(Invalid, match='not "probe"'):
        probe = FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=DAY)
        await service.register(project.id, **page, freshness=probe)
    with pytest.raises(Invalid, match='format "html"'):
        await service.register(project.id, **(page | {"format": DataFormat.CSV}))
    with pytest.raises(Invalid, match="needs a declared schema"):
        await service.register(
            project.id, **page, options={"operation": "answers", "task": "x", "json_format": {}}
        )

    crawl = await service.register(
        project.id,
        **page,
        options={"operation": "crawl", "max_pages": 2},
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=7 * DAY),
    )
    assert [c.name for c in crawl.declared_schema.columns] == ["page", "text"]  # type: ignore[union-attr]
    assert (await service.refresh(crawl.id, force=True)).changed

    clock.advance(days=6)
    with pytest.raises(Invalid, match="can be refreshed again from 2026-01-08 12:00 UTC"):
        await service.refresh(crawl.id, force=True)
    clock.advance(days=1)
    await service.refresh(crawl.id, force=True)
    assert [name for name, _ in explorer.calls] == ["crawl", "crawl"]


# Context.dev and the budget's table


async def test_context_dev_gets_only_the_forwarded_parameters_and_its_refusals_read_well() -> None:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/web/urls"):
            return httpx.Response(402, json={"message": "Usage exceeded"})
        return httpx.Response(
            200,
            json={
                "url": "https://example.test/",
                "markdown": {"requested": True, "success": True, "data": "# Hi"},
                "metadata": {"title": "Hi"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        web = ContextDevWeb(client, "key")
        page = await web.read("https://example.test", tags=["ada", "project:p"])
        with pytest.raises(Invalid, match="no credits left: Usage exceeded"):
            await web.map("thl.fi", search=None, max_links=5, tags=["ada", "project:p"])

    assert page == WebPage(url="https://example.test/", title="Hi", markdown="# Hi")
    assert json.loads(sent[0].content) == {
        "url": "https://example.test",
        "formats": {"markdown": True},
        "tags": ["ada", "project:p"],
    }
    assert sent[0].headers["authorization"] == "Bearer key"
    assert dict(sent[1].url.params) == {
        "domain": "thl.fi",
        "maxLinks": "5",
        "tags": "ada,project:p",
    }


async def test_the_web_budget_counts_in_its_own_transaction(migrated_database_url: str) -> None:
    day = date(2026, 1, 1)
    async with engine_for(migrated_database_url) as engine:
        async with unit_of_work(engine) as repos:
            project = factories.project()
            await repos.projects.add(project)
        budget = SqlWebBudget(engine)

        assert await budget.spend(project.id, day, 3, limit=4)
        assert not await budget.spend(project.id, day, 2, limit=4)
        assert await budget.spend(project.id, day, 1, limit=4)
        await budget.adjust(project.id, day, -2)
        assert await budget.spend(project.id, day, 2, limit=4)
        assert not await budget.spend(project.id, day + timedelta(days=1), 5, limit=4)
