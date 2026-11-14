"""The HTTP source readers, against a transport that answers in process."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import factories
from ada.adapters.sources.http import (
    USER_AGENT,
    HttpSourceReaders,
    SourceUnavailable,
    create_client,
)
from ada.core.models.errors import Invalid
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from fakes import FixedClock

pytestmark = pytest.mark.anyio

type Handler = Callable[[httpx.Request], httpx.Response]


class Server:
    """Answers with `handler` and keeps every request it saw."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def readers(server: Server) -> HttpSourceReaders:
    return HttpSourceReaders(create_client(httpx.MockTransport(server)), FixedClock())


def source(kind: AccessKind = AccessKind.URL, **changes: Any) -> DataSource:
    return factories.data_source(factories.project().id, access_kind=kind, **changes)


async def test_a_url_source_is_fetched_with_get() -> None:
    server = Server(lambda request: httpx.Response(200, content=b"a,b\n1,2\n"))
    reader = readers(server).for_kind(AccessKind.URL)

    fetched = await reader.fetch(
        source(address="https://x.test/data?years=2023&years=2024"), TimeRange()
    )

    assert (fetched.content, fetched.format) == (b"a,b\n1,2\n", DataFormat.CSV)
    assert fetched.origin == "https://x.test/data?years=2023&years=2024"
    assert fetched.fetched_at == FixedClock().now()
    [request] = server.requests
    assert request.method == "GET"
    assert request.headers["user-agent"] == USER_AGENT


async def test_params_and_headers_are_added_to_the_address() -> None:
    server = Server(lambda request: httpx.Response(200, json=[]))
    reader = readers(server).for_kind(AccessKind.URL)
    options = {"params": {"genders": "total", "years": [2023, 2024]}, "headers": {"X-Key": "k"}}

    await reader.fetch(
        source(address="https://x.test/data?indicator=3621", options=options), TimeRange()
    )

    [request] = server.requests
    assert str(request.url) == (
        "https://x.test/data?indicator=3621&genders=total&years=2023&years=2024"
    )
    assert request.headers["x-key"] == "k"


async def test_a_request_source_sends_its_method_headers_and_body() -> None:
    server = Server(lambda request: httpx.Response(200, content=b"a\n1\n"))
    reader = readers(server).for_kind(AccessKind.REQUEST)
    options = {
        "body": {"query": [], "response": {"format": "csv"}},
        "headers": {"Accept": "text/csv"},
    }

    await reader.fetch(source(AccessKind.REQUEST, options=options), TimeRange())

    [request] = server.requests
    assert request.method == "POST"
    assert json.loads(request.content) == {"query": [], "response": {"format": "csv"}}
    assert request.headers["accept"] == "text/csv"


async def test_a_request_source_can_send_a_text_body_with_any_method() -> None:
    server = Server(lambda request: httpx.Response(200, content=b""))
    reader = readers(server).for_kind(AccessKind.REQUEST)

    await reader.fetch(
        source(AccessKind.REQUEST, options={"method": "PUT", "body": "q=1"}), TimeRange()
    )

    [request] = server.requests
    assert (request.method, request.content) == ("PUT", b"q=1")


async def test_a_url_source_ignores_method_and_body() -> None:
    server = Server(lambda request: httpx.Response(200, content=b""))
    reader = readers(server).for_kind(AccessKind.URL)

    await reader.fetch(source(options={"method": "POST", "body": {"q": 1}}), TimeRange())

    [request] = server.requests
    assert (request.method, request.content) == ("GET", b"")


async def test_an_error_answer_makes_the_source_unavailable() -> None:
    server = Server(lambda request: httpx.Response(503))
    reader = readers(server).for_kind(AccessKind.URL)

    with pytest.raises(SourceUnavailable, match=r"GET https://example.test/data.csv answered 503"):
        await reader.fetch(source(), TimeRange())


async def test_an_unreachable_server_makes_the_source_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    reader = readers(Server(refuse)).for_kind(AccessKind.URL)

    with pytest.raises(SourceUnavailable, match="connection refused"):
        await reader.fetch(source(), TimeRange())


@pytest.mark.parametrize(
    "changes",
    [
        {"address": "ftp://x.test/data.csv"},
        {"options": {"headers": "not a mapping"}},
        {"options": {"probe": {"field": "data-updated"}}},
    ],
)
async def test_a_source_the_reader_cannot_use_is_invalid(changes: dict[str, Any]) -> None:
    reader = readers(Server(lambda request: httpx.Response(200))).for_kind(AccessKind.URL)

    with pytest.raises(Invalid):
        await reader.fetch(source(**changes), TimeRange())


async def test_the_probe_reads_a_declared_field() -> None:
    server = Server(
        lambda request: httpx.Response(200, json={"id": 3621, "data-updated": "2026-06-12"})
    )
    reader = readers(server).for_kind(AccessKind.URL)
    probe = {"url": "https://x.test/indicators/3621", "field": "data-updated"}

    assert await reader.probe(source(options={"probe": probe})) == "2026-06-12"
    [request] = server.requests
    assert (request.method, str(request.url)) == ("GET", "https://x.test/indicators/3621")


async def test_the_probe_reads_a_nested_field() -> None:
    server = Server(lambda request: httpx.Response(200, json={"meta": {"updated": 5}}))
    reader = readers(server).for_kind(AccessKind.URL)

    token = await reader.probe(
        source(options={"probe": {"url": "https://x.test/m", "field": "meta.updated"}})
    )

    assert token == "5"


async def test_a_probe_without_a_field_hashes_the_answer() -> None:
    answers = iter([b"v1", b"v1", b"v2"])
    server = Server(lambda request: httpx.Response(200, content=next(answers)))
    reader = readers(server).for_kind(AccessKind.URL)
    probed = source(options={"probe": {"url": "https://x.test/meta"}})

    tokens = [await reader.probe(probed) for _ in range(3)]

    assert tokens[0] == tokens[1] != tokens[2]
    assert tokens[0].startswith("sha256:")


async def test_a_declared_probe_without_its_field_fails() -> None:
    server = Server(lambda request: httpx.Response(200, json={"id": 1}))
    reader = readers(server).for_kind(AccessKind.URL)

    with pytest.raises(Invalid, match="data-updated"):
        await reader.probe(
            source(options={"probe": {"url": "https://x.test/m", "field": "data-updated"}})
        )


@pytest.mark.parametrize(
    ("headers", "token"),
    [
        ({"ETag": '"abc"', "Last-Modified": "Fri, 13 Nov 2026 10:00:00 GMT"}, 'etag:"abc"'),
        (
            {"Last-Modified": "Fri, 13 Nov 2026 10:00:00 GMT"},
            "last-modified:Fri, 13 Nov 2026 10:00:00 GMT",
        ),
        ({}, None),
    ],
)
async def test_without_a_declared_probe_the_http_validator_is_the_token(
    headers: dict[str, str], token: str | None
) -> None:
    server = Server(lambda request: httpx.Response(200, headers=headers))
    reader = readers(server).for_kind(AccessKind.URL)

    assert await reader.probe(source()) == token
    [request] = server.requests
    assert (request.method, str(request.url)) == ("HEAD", "https://example.test/data.csv")


async def test_a_server_that_refuses_head_offers_no_token() -> None:
    server = Server(lambda request: httpx.Response(405))
    reader = readers(server).for_kind(AccessKind.URL)

    assert await reader.probe(source()) is None


async def test_a_post_request_source_has_no_http_validator() -> None:
    server = Server(lambda request: httpx.Response(200, headers={"ETag": '"abc"'}))
    reader = readers(server).for_kind(AccessKind.REQUEST)

    assert await reader.probe(source(AccessKind.REQUEST, options={"body": {"q": 1}})) is None
    assert server.requests == []


@pytest.mark.parametrize("kind", [AccessKind.BROWSER, AccessKind.DOCUMENT])
async def test_browser_and_document_sources_are_not_installed_yet(kind: AccessKind) -> None:
    with pytest.raises(Invalid, match="not installed yet"):
        readers(Server(lambda request: httpx.Response(200))).for_kind(kind)
