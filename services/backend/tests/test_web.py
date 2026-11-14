"""The web tools against recorded Exa and Context.dev answers (tests/recordings/web.json)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from ada.adapters.sources.http import create_client
from ada.adapters.web.context import ContextPages
from ada.adapters.web.exa import DATA_DOMAINS, ExaSearch
from ada.core.models.errors import Invalid
from ada.core.models.web import SearchScope
from fakes import WebReplay

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
