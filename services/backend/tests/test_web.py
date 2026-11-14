"""The web tools against recorded Exa and Context.dev answers (tests/recordings/web.json)."""

import json
from uuid import uuid7

import httpx
import pytest
from dishka import Provider, Scope, provide
from pydantic import SecretStr

from ada.adapters.sources.http import create_client
from ada.adapters.web.context import ContextPages
from ada.adapters.web.exa import DATA_DOMAINS, ExaSearch
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.web import SearchHit, SearchScope
from ada.core.ports.web import PageReader, WebSearch
from ada.entrypoints.mcp.agent import InProcessToolbox
from api_support import call, mcp_client
from fakes import FakePageReader, FakeWebSearch, WebReplay

pytestmark = pytest.mark.anyio
KEY = SecretStr("test-key")
PAGE = "https://sotkanet.fi/sotkanet/en/metadata/indicators/3625"


def client(replay: WebReplay) -> httpx.AsyncClient:
    return create_client(httpx.MockTransport(replay))


async def test_exa_search_sends_data_domains_and_parses_hits() -> None:
    replay = WebReplay()
    async with client(replay) as http:
        hits = await ExaSearch(http, KEY).search(
            "cancer survival by hospital district Finland", SearchScope.DATA, 5
        )
    assert json_body(replay)["includeDomains"] == DATA_DOMAINS
    assert replay.requests[0].headers["Authorization"] == "Bearer test-key"
    assert hits
    assert all(hit.url.startswith("https://") and hit.title for hit in hits)


async def test_exa_contents_returns_page_text() -> None:
    async with client(WebReplay()) as http:
        pages = await ExaSearch(http, KEY).contents([PAGE])
    assert [page.url for page in pages] == [PAGE]
    assert "survival" in pages[0].text


async def test_context_read_and_extract() -> None:
    async with client(WebReplay()) as http:
        reader = ContextPages(http, KEY)
        page = await reader.read(PAGE)
        rows = await reader.extract(
            PAGE,
            "Return the metadata table of the indicator (name/value pairs). "
            "Use only facts stated on the page.",
            ["field", "value"],
        )
    assert page.text.startswith("# Five-year relative survival")
    assert page.title
    assert rows
    assert all(set(row) == {"field", "value"} for row in rows)


async def test_monitor_secret_comes_from_the_response() -> None:
    replay = WebReplay()
    async with client(replay) as http:
        reader = ContextPages(http, KEY)
        monitor = await reader.watch(
            "https://example.com/", "https://example.com/api/hooks/context/probe"
        )
        await reader.unwatch(monitor.id)
    assert monitor.secret.get_secret_value() == "test-secret"
    assert "secret" not in json_body(replay)["webhook"]
    assert replay.requests[1].method == "DELETE"


async def test_missing_key_fails_clearly() -> None:
    async with client(WebReplay()) as http:
        with pytest.raises(Invalid, match="web search is not configured: EXA_API_KEY is not set"):
            await ExaSearch(http, None).search("x", SearchScope.ANY, 1)
        with pytest.raises(
            Invalid, match="page reading is not configured: CONTEXT_API_KEY is not set"
        ):
            await ContextPages(http, None).read(PAGE)


def json_body(replay: WebReplay) -> dict[str, dict[str, object]]:
    body: dict[str, dict[str, object]] = json.loads(replay.requests[0].content)
    return body


async def test_error_answers_never_quote_the_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(401, text="Invalid key synthetic-secret-key")
        if request.url.path.endswith("/web/scrape"):
            return httpx.Response(
                400,
                json={"error_code": "INPUT_VALIDATION_ERROR", "message": "synthetic-secret-key"},
            )
        return httpx.Response(200, text="<html>not json</html>")

    secret = SecretStr("synthetic-secret-key")
    async with create_client(httpx.MockTransport(handler)) as http:
        with pytest.raises(Unavailable, match="401") as search:
            await ExaSearch(http, secret).search("x", SearchScope.ANY, 1)
        with pytest.raises(Unavailable, match="INPUT_VALIDATION_ERROR") as scrape:
            await ContextPages(http, secret).read(PAGE)
        with pytest.raises(Unavailable, match="other than JSON"):
            await ContextPages(http, secret).unwatch("mon_1")
    assert "synthetic-secret-key" not in str(search.value) + str(scrape.value)


class FakeWeb(Provider):
    def __init__(self, search: FakeWebSearch, pages: FakePageReader) -> None:
        super().__init__()
        self.search, self.pages = search, pages

    @provide(scope=Scope.APP)
    def search_(self) -> WebSearch:
        return self.search

    @provide(scope=Scope.APP)
    def pages_(self) -> PageReader:
        return self.pages


WEB_TOOLS = {"search_web", "read_page", "extract_table"}


async def test_web_tools_are_listed_for_the_agent(unreachable_settings: Settings) -> None:
    agent = Actor(kind=ActorKind.AGENT, name="gemini/flash")
    async with mcp_client(unreachable_settings) as (_, seen):
        async with InProcessToolbox(seen.container).connect(agent, uuid7()) as tools:
            specs = {spec.name: spec for spec in tools.specs()}
    assert WEB_TOOLS <= set(specs)
    assert all("session_id" in specs[name].input_schema["properties"] for name in WEB_TOOLS)


async def test_web_tools_use_the_ports(unreachable_settings: Settings) -> None:
    hit = SearchHit(url="https://stat.fi/a", title="A", snippet="s")
    search = FakeWebSearch(hits=[hit] * 3)
    pages = FakePageReader(text="x" * 25_000, rows=[{"field": "n", "value": "1"}])
    async with mcp_client(unreachable_settings, FakeWeb(search, pages)) as (client, _):
        hits = await call(client, "search_web", query="survival", scope="news", limit=2)
        page = await call(client, "read_page", url="https://stat.fi/a")
        rows = await call(
            client, "extract_table", url="https://stat.fi/a", instruction="t", columns=["field"]
        )
    assert [h["url"] for h in hits] == ["https://stat.fi/a"] * 2
    assert search.searches == [("survival", SearchScope.NEWS, 2)]
    assert page["text"].startswith("x" * 20_000)
    assert "truncated" in page["text"][20_000:]
    assert len(page["text"]) < 20_500
    assert rows == [{"field": "n", "value": "1"}]
    assert ("extract", ("https://stat.fi/a", "t", ("field",))) in pages.calls


async def test_web_tools_without_keys_fail_with_the_setting_named(
    unreachable_settings: Settings,
) -> None:
    async with mcp_client(unreachable_settings) as (client, _):
        with pytest.raises(Exception, match="EXA_API_KEY is not set"):
            await client.call_tool("search_web", {"query": "x"})
        with pytest.raises(Exception, match="CONTEXT_API_KEY is not set"):
            await client.call_tool("read_page", {"url": "https://example.com"})


async def test_system_status_reports_web_configuration(unreachable_settings: Settings) -> None:
    async def flags(settings: Settings) -> list[object]:
        async with mcp_client(settings) as (client, _):
            status = await call(client, "system_status")
        return [status[k] for k in ("web_search", "page_reading", "watching")]

    keyed = unreachable_settings.model_copy(
        update={"exa_api_key": SecretStr("k"), "context_api_key": SecretStr("k")}
    )
    assert await flags(unreachable_settings) == [False, False, False]
    assert await flags(keyed) == [True, True, False]
    full = keyed.model_copy(update={"ada_public_url": "https://ada.example"})
    assert await flags(full) == [True, True, True]
