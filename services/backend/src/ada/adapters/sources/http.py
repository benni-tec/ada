"""Reading URL and request sources over HTTP.

These keys of `DataSource.options` control the readers; shaping the answer into a table
has its own keys (ada.core.services.sources.shaping).

`headers`
    {name: value}, sent with every request of the source, the probe's included.
`params`
    {name: value or [values]}, query parameters added to the address; one named here
    replaces all of that name in the address. Repeated parameters, such as Sotkanet's
    `years`, can also stay in the address itself.
`method` (request sources)
    The HTTP method; POST when there is a body, otherwise GET.
`body` (request sources)
    An object or array is sent as JSON, a string as it is.
`probe`
    {"url": ..., "field": ..., "headers": {...}}: how to ask cheaply whether the data
    changed. The url is fetched with GET; `field` is a dot path into its JSON answer whose
    value is the token, e.g. Sotkanet's "data-updated". Without `field` the token is a
    hash of the whole answer, which suits a small metadata document. Without `probe`, the
    ETag or Last-Modified of a HEAD request to the address is the token, when the server
    sends one and the source is read with GET.

A URL source is always read with GET; `method` and `body` belong to request sources.

Addresses come from people and from the research agent, which takes them from the web, so
every request, redirects included, goes only to public addresses unless the platform
allows private ones (local development and tests), and an answer is read up to a limit.
Document sources at a URL are downloaded by the URL reader, so the same holds for them.

Time ranges. The readers send what the options say and nothing more. A source that can be
asked for some periods only declares `pushdown` in its options, and the source service
writes the requested periods into `params` or `body` before it calls the reader
(ada.core.services.sources.pushdown), so the reader needs no notion of periods.
"""

import asyncio
import hashlib
import ipaddress
import json
import socket
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import Field, ValidationError

from ada.adapters.sources.context_dev import ContextDevParser
from ada.adapters.sources.document import DocumentReader
from ada.adapters.sources.web import WebPageReader
from ada.adapters.web.context_dev import ContextDevWeb
from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, Id
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.sources import AccessKind, DataSource, StoredFile
from ada.core.models.time import TimeRange
from ada.core.ports.sources import FileStore, SourceReader, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget

# Names us to the services we read, as their terms usually ask.
USER_AGENT = "ADA/0.1 (traceable data analysis; +https://github.com/benni-tec/ada)"
HTTP_KINDS = (AccessKind.URL, AccessKind.REQUEST)
# Statistics APIs can take a while to assemble a table, but not minutes.
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
MAX_REDIRECTS = 10
# Far above any statistics table or boundary file the demo reads.
MAX_BYTES = 50_000_000

type Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
type Params = dict[str, str | int | float | list[str | int | float]]


class ProbeOptions(DomainModel):
    url: str = Field(min_length=1)
    field: str | None = None
    headers: dict[str, str] = {}


class HttpOptions(DomainModel):
    headers: dict[str, str] = {}
    params: Params = {}
    method: Method | None = None
    body: dict[str, Any] | list[Any] | str | None = None
    probe: ProbeOptions | None = None


class SourceUnavailable(Unavailable):
    """The source could not be reached or answered with an error. Its message is what the
    source records as its last error, so it says which request failed and how."""


def create_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The client every HTTP reader shares, for its connection pool. Tests pass a
    transport that replays recorded answers."""
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


class HttpReader(SourceReader):
    """Reads URL sources (GET the address) or request sources (method, headers and body
    from the options)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        clock: Clock,
        kind: AccessKind,
        allow_private: bool = False,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        if kind not in (AccessKind.URL, AccessKind.REQUEST):
            raise ValueError(f"HTTP reads URL and request sources, not {kind.value}")
        self.client = client
        self.clock = clock
        self.kind = kind
        self.allow_private = allow_private
        self.max_bytes = max_bytes

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        # The time range is already in the options where the source can take it (see the
        # module's docstring); it is not sent a second time.
        options = _options(source)
        method = self._method(options)
        body = options.body if self.kind is AccessKind.REQUEST else None
        response = await self._send(
            method,
            _url(source, options),
            headers=options.headers,
            json=body if isinstance(body, dict | list) else None,
            content=body if isinstance(body, str) else None,
        )
        return FetchedData(
            content=response.content,
            format=source.format,
            fetched_at=self.clock.now(),
            origin=str(response.url),
        )

    async def probe(self, source: DataSource) -> str | None:
        options = _options(source)
        if options.probe is not None:
            return await self._declared_probe(options.probe, options.headers)
        if self._method(options) != "GET":
            # A validator of the address describes what GET returns, not what a POST does.
            return None
        response = await self._send(
            "HEAD", _url(source, options), headers=options.headers, ok=False
        )
        if response.is_error:
            # Plenty of APIs answer HEAD with 405; that only means there is no cheap check.
            return None
        if etag := response.headers.get("etag"):
            return f"etag:{etag}"
        if last_modified := response.headers.get("last-modified"):
            return f"last-modified:{last_modified}"
        return None

    async def _declared_probe(self, probe: ProbeOptions, headers: dict[str, str]) -> str:
        response = await self._send("GET", probe.url, headers=headers | probe.headers)
        if probe.field is None:
            return "sha256:" + hashlib.sha256(response.content).hexdigest()
        try:
            found: Any = response.json()
        except ValueError:
            raise Invalid(f"The probe {probe.url} did not answer with JSON") from None
        for segment in probe.field.split("."):
            found = found.get(segment) if isinstance(found, dict) else None
        if found is None:
            raise Invalid(f"The probe {probe.url} has no field {probe.field!r}")
        if isinstance(found, dict | list):
            return json.dumps(found, sort_keys=True, separators=(",", ":"))
        return str(found)

    def _method(self, options: HttpOptions) -> str:
        if self.kind is AccessKind.URL:
            return "GET"
        return options.method or ("POST" if options.body is not None else "GET")

    async def _send(
        self, method: str, url: str | httpx.URL, ok: bool = True, **kwargs: Any
    ) -> httpx.Response:
        """Send one request, following redirects here so each address is checked before it
        is asked. Raises SourceUnavailable when it fails, and when the answer is an error
        unless `ok` is False."""
        request = self.client.build_request(method, url, **kwargs)
        for _ in range(MAX_REDIRECTS + 1):
            if not self.allow_private:
                await _check_public(request.url)
            try:
                response = await self.client.send(request, stream=True, follow_redirects=False)
                try:
                    if response.next_request is not None:
                        request = response.next_request
                        continue
                    if ok and response.is_error:
                        raise SourceUnavailable(
                            f"{method} {url} answered {response.status_code}"
                            f" {response.reason_phrase}"
                        )
                    return await self._read(response, f"{method} {url}")
                finally:
                    await response.aclose()
            except httpx.HTTPError as error:
                reason = str(error) or type(error).__name__
                raise SourceUnavailable(f"{method} {url} failed: {reason}") from error
        raise SourceUnavailable(f"{method} {url} redirected more than {MAX_REDIRECTS} times")

    async def _read(self, response: httpx.Response, call: str) -> httpx.Response:
        """The answer with its whole body, which may be at most max_bytes once decoded."""
        too_large = SourceUnavailable(
            f"{call} answered more than {self.max_bytes:,} bytes, the most a source may have"
        )
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > self.max_bytes:
            raise too_large
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content += chunk
            if len(content) > self.max_bytes:
                raise too_large
        # The body is decoded already: the headers must no longer say how it was encoded.
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name not in ("content-encoding", "content-length")
        ]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=bytes(content),
            request=response.request,
            extensions=response.extensions,
        )


class HttpSourceReaders(SourceReaders):
    """The installed readers: URL, request, document and web sources, which all go over
    HTTP. Browser sources come later. Web sources spend the project's credits in
    `web_budget`; without one they cannot be read."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        clock: Clock,
        files: FileStore | None = None,
        context_dev_key: str | None = None,
        web_budget: WebBudget | None = None,
        web_daily_credit_limit: int = 0,
        allow_private: bool = False,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self.readers: dict[AccessKind, SourceReader] = {
            kind: HttpReader(client, clock, kind, allow_private, max_bytes) for kind in HTTP_KINDS
        }
        self.readers[AccessKind.DOCUMENT] = DocumentReader(
            self.readers[AccessKind.URL],
            files or _NoUploads(),
            ContextDevParser(client, context_dev_key),
            clock,
        )
        self.readers[AccessKind.WEB] = WebPageReader(
            ContextDevWeb(client, context_dev_key),
            web_budget or _NoWebBudget(),
            clock,
            web_daily_credit_limit,
        )

    def for_kind(self, kind: AccessKind) -> SourceReader:
        try:
            return self.readers[kind]
        except KeyError:
            raise Invalid(f"Reading {kind.value} sources is not installed yet") from None


class _NoUploads(FileStore):
    """For readers made without a file store, e.g. in tests that never upload."""

    async def put(self, project_id: Id, content: bytes, suffix: str) -> StoredFile:
        raise Invalid("Uploading files is not available here")

    async def get(self, address: str) -> bytes:
        raise Invalid("Uploaded files are not available here")


class _NoWebBudget(WebBudget):
    """For readers made without a budget, e.g. in tests that read no web source."""

    async def spend(self, project_id: Id, day: date, credits: int, limit: int) -> bool:
        raise Invalid("Web sources are not available here")

    async def adjust(self, project_id: Id, day: date, credits: int) -> None:
        return None


def _options(source: DataSource) -> HttpOptions:
    keys = HttpOptions.model_fields.keys()
    try:
        return HttpOptions.model_validate({k: v for k, v in source.options.items() if k in keys})
    except ValidationError as error:
        raise Invalid(f"Invalid options for source {source.name}: {error}") from None


def _url(source: DataSource, options: HttpOptions) -> httpx.URL:
    if not source.address.startswith(("http://", "https://")):
        raise Invalid(f"The address of source {source.name} is not an http(s) URL")
    try:
        # Merged here because httpx's `params` would replace the query the address has.
        return httpx.URL(source.address).copy_merge_params(options.params)
    except httpx.InvalidURL as error:
        raise Invalid(f"The address of source {source.name} is not a URL: {error}") from None


async def _check_public(url: httpx.URL) -> None:
    """Raises Invalid unless every address the host resolves to is public: not loopback,
    private, link-local (cloud metadata services), multicast or unspecified."""
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        found = await asyncio.get_running_loop().getaddrinfo(
            url.host, port, type=socket.SOCK_STREAM
        )
    except OSError as error:
        raise SourceUnavailable(f"{url.host} could not be resolved: {error}") from None
    for *_, address in found:
        ip = ipaddress.ip_address(address[0])
        if ip.is_multicast or not ip.is_global:
            raise Invalid(
                f"{url.host} is not a public address ({ip}); sources read public addresses only"
            )
