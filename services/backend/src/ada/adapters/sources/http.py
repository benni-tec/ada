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
`paginate` (JSON)
    {"token": "nextPageToken", "param": "pageToken"} follows a response token in
    a query parameter; {"more": "pagination.nextPage", "page": "pagination.page"}
    increments an integer in the request's JSON body while `more` is truthy. For URL
    sources `page` names a query parameter, starting at its value or 1. Response paths
    and body paths use dots, with digit segments indexing arrays. Pages keep the first
    document's metadata and concatenate the arrays at `rows`, or the top-level arrays
    without `rows`, before shaping. `max_pages` defaults to 20 (1–100); more pages are an
    error. `delay_seconds` defaults to 1 (0 allowed). All pages share the byte limit.
`probe`
    {"url": ..., "field": ..., "headers": {...}} asks cheaply whether data changed.
    `field` is a dot path into the JSON answer; digit segments index arrays. Alternatively
    `fields` is a list of paths whose values form a JSON array token, in order. Missing
    or null values are errors. `method` defaults to GET; `body` sends JSON, e.g. with
    `method: "POST"` for a search API. Source headers apply, with probe headers overriding
    them. Without `field` or `fields` the token hashes the whole answer. Without `probe`,
    ETag or Last-Modified from HEAD is the token when the source is read with GET.

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
import contextlib
import copy
import functools
import hashlib
import ipaddress
import json
import socket
import zlib
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal, cast

import httpcore
import httpx
from httpx._utils import get_environment_proxies
from pydantic import Field, ValidationError, model_validator

from ada.adapters.sources.context_dev import ContextDevParser
from ada.adapters.sources.document import DocumentReader
from ada.adapters.sources.web import WebPageReader
from ada.adapters.web.context_dev import ContextDevWeb
from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, Id
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.sources import AccessKind, DataFormat, DataSource, StoredFile
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
# The content encodings asked for, which the readers undo within MAX_BYTES (_Inflate).
ENCODINGS = ("gzip", "deflate")

type Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
type Params = dict[str, str | int | float | list[str | int | float]]


class ProbeOptions(DomainModel):
    url: str = Field(min_length=1)
    field: str | None = None
    headers: dict[str, str] = {}
    fields: list[str] | None = Field(default=None, min_length=1)
    method: Method = "GET"
    body: dict[str, Any] | list[Any] | None = None


class PaginateOptions(DomainModel, extra="forbid"):
    token: str | None = Field(default=None, min_length=1)
    param: str | None = Field(default=None, min_length=1)
    more: str | None = Field(default=None, min_length=1)
    page: str | None = Field(default=None, min_length=1)
    max_pages: int = Field(default=20, ge=1, le=100, strict=True)
    delay_seconds: float = Field(default=1, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _style(self) -> PaginateOptions:
        if not (
            (self.token and self.param and self.more is None and self.page is None)
            or (self.more and self.page and self.token is None and self.param is None)
        ):
            raise ValueError(
                'Use {"token": "nextPageToken", "param": "pageToken"} '
                'or {"more": "pagination.nextPage", "page": "pagination.page"}'
            )
        return self


class HttpOptions(DomainModel):
    headers: dict[str, str] = {}
    params: Params = {}
    method: Method | None = None
    body: dict[str, Any] | list[Any] | str | None = None
    probe: ProbeOptions | None = None
    paginate: PaginateOptions | None = None


class SourceUnavailable(Unavailable):
    """The source could not be reached or answered with an error. Its message is what the
    source records as its last error, so it says which request failed and how."""


def create_client(
    transport: httpx.AsyncBaseTransport | None = None, allow_private: bool = False
) -> httpx.AsyncClient:
    """The client every HTTP reader shares, for its connection pool. It connects to
    public addresses only (_PublicNetwork) unless private ones are allowed. Behind a proxy
    from the environment (HTTP_PROXY and the like) the proxy makes the connections, so
    only the check of each address before it is asked (_check_public) applies. Tests pass
    a transport that replays recorded answers."""
    if transport is None and not allow_private and not get_environment_proxies():
        transport = _public_transport()
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": ", ".join(ENCODINGS)},
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
        url = _url(source, options)
        pagination = options.paginate
        if pagination and source.format is not DataFormat.JSON:
            raise Invalid("paginate requires JSON format")
        body = copy.deepcopy(body)
        page_number = None
        if pagination and pagination.page:
            if self.kind is AccessKind.REQUEST:
                page_number = _at(body, pagination.page)
                if type(page_number) is not int:
                    raise Invalid("paginate.page must point to an integer in the JSON body")
            else:
                try:
                    page_number = int(url.params.get(pagination.page, "1"))
                except ValueError:
                    raise Invalid("paginate.page query parameter must be an integer") from None
                url = url.copy_set_param(pagination.page, page_number)
        total = 0
        origin = None
        document: Any = None
        combined: list[Any] = []
        for number in range(1, (pagination.max_pages if pagination else 1) + 1):
            response = await self._send(
                method,
                url,
                headers=options.headers,
                json=body if isinstance(body, dict | list) else None,
                content=body if isinstance(body, str) else None,
                byte_limit=self.max_bytes - total,
            )
            origin = origin or str(response.url)
            total += len(response.content)
            if not pagination:
                content = response.content
                break
            try:
                answer = response.json()
            except ValueError:
                raise Invalid("Paginated source did not answer with JSON") from None
            rows_path = source.options.get("rows")
            rows = _at(answer, rows_path) if rows_path else answer
            if not isinstance(rows, list):
                raise Invalid("paginate requires an array at rows (or a top-level array)")
            if number == 1:
                document = answer
            combined.extend(rows)
            next_value = _at(answer, pagination.token or pagination.more or "")
            if pagination.token and next_value is not None and not isinstance(next_value, str):
                raise Invalid("paginate.token must point to a string or null")
            if not next_value:
                if rows_path:
                    _replace(document, rows_path, combined)
                else:
                    document = combined
                content = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
                if len(content) > self.max_bytes:
                    raise SourceUnavailable("Paginated source exceeds max_bytes")
                break
            if number == pagination.max_pages:
                raise SourceUnavailable(f"Pagination exceeded max_pages ({pagination.max_pages})")
            if pagination.token:
                url = url.copy_set_param(pagination.param or "", next_value)
            else:
                assert page_number is not None
                page_number += 1
                if self.kind is AccessKind.REQUEST:
                    _replace(body, pagination.page or "", page_number)
                else:
                    url = url.copy_set_param(pagination.page or "", page_number)
            await asyncio.sleep(pagination.delay_seconds)
        return FetchedData(
            content=content,
            format=source.format,
            fetched_at=self.clock.now(),
            origin=origin,
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
        response = await self._send(
            probe.method, probe.url, headers=headers | probe.headers, json=probe.body
        )
        if probe.field is None and probe.fields is None:
            return "sha256:" + hashlib.sha256(response.content).hexdigest()
        try:
            found: Any = response.json()
        except ValueError:
            raise Invalid(f"The probe {probe.url} did not answer with JSON") from None
        paths = probe.fields if probe.fields is not None else [probe.field or ""]
        values = [_at(found, path) for path in paths]
        for path, value in zip(paths, values, strict=True):
            if value is None:
                raise Invalid(f"The probe {probe.url} has no field {path!r}")
        found = values if probe.fields is not None else values[0]
        if isinstance(found, dict | list):
            return json.dumps(found, sort_keys=True, separators=(",", ":"))
        return str(found)

    def _method(self, options: HttpOptions) -> str:
        if self.kind is AccessKind.URL:
            return "GET"
        return options.method or ("POST" if options.body is not None else "GET")

    async def _send(
        self,
        method: str,
        url: str | httpx.URL,
        ok: bool = True,
        byte_limit: int | None = None,
        **kwargs: Any,
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
                    return await self._read(response, f"{method} {url}", byte_limit)
                finally:
                    await response.aclose()
            except httpx.HTTPError as error:
                reason = str(error) or type(error).__name__
                raise SourceUnavailable(f"{method} {url} failed: {reason}") from error
        raise SourceUnavailable(f"{method} {url} redirected more than {MAX_REDIRECTS} times")

    async def _read(
        self, response: httpx.Response, call: str, byte_limit: int | None = None
    ) -> httpx.Response:
        """The answer with its whole body, which may be at most max_bytes once decoded."""
        limit = self.max_bytes if byte_limit is None else byte_limit
        too_large = SourceUnavailable(
            f"{call} answered more than {limit:,} bytes, the most a source may have"
        )
        length = response.headers.get("content-length", "")
        # A HEAD answer has no body: its length is that of what GET would send.
        head = response.request.method == "HEAD"
        if not head and length.isdigit() and int(length) > limit:
            raise too_large
        # Decoded here, since httpx's decoders take no limit and a few kilobytes of gzip
        # can hold gigabytes. Last applied, first undone.
        encodings = response.headers.get_list("content-encoding", split_commas=True)
        decoders = [
            _Inflate(name, limit, too_large)
            for name in reversed([encoding.strip().lower() for encoding in encodings])
            if name in ENCODINGS
        ]
        content = bytearray()
        # The bytes as sent. aiter_raw would refuse them for an answer that a test transport
        # built from bytes, which httpx reads (and decodes) at once.
        async for chunk in cast(httpx.AsyncByteStream, response.stream):
            for decoder in decoders:
                chunk = decoder.decode(chunk)
            content += chunk
            if len(content) > limit:
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


class _Inflate:
    """Undoes one gzip or deflate encoding, raising `too_large` once it would give more
    than `limit` bytes, before it holds them."""

    def __init__(self, encoding: str, limit: int, too_large: Exception) -> None:
        self.encoding = encoding
        self.wbits = zlib.MAX_WBITS | 16 if encoding == "gzip" else zlib.MAX_WBITS
        self.inflater = zlib.decompressobj(self.wbits)
        self.limit = limit
        self.too_large = too_large
        self.size = 0

    def decode(self, data: bytes) -> bytes:
        decoded = bytearray()
        while data and not self.inflater.eof:
            try:
                piece = self.inflater.decompress(data, self.limit - self.size + 1)
            except zlib.error as error:
                if self.size == 0 and self.wbits == zlib.MAX_WBITS:
                    # Deflate is meant to have zlib's header; some servers leave it out.
                    self.wbits = -zlib.MAX_WBITS
                    self.inflater = zlib.decompressobj(self.wbits)
                    continue
                message = f"the answer is not valid {self.encoding}: {error}"
                raise httpx.DecodingError(message) from None
            self.size += len(piece)
            if self.size > self.limit:
                raise self.too_large
            decoded += piece
            data = self.inflater.unconsumed_tail
        return bytes(decoded)


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
        raise Invalid(
            f"Invalid options for source {source.name}: {error}. "
            'Example paginate: {"token": "nextPageToken", "param": "pageToken"}'
        ) from None


def _at(document: Any, path: str) -> Any:
    found = document
    for segment in path.split("."):
        if isinstance(found, dict):
            found = found.get(segment)
        elif isinstance(found, list) and segment.isdigit() and int(segment) < len(found):
            found = found[int(segment)]
        else:
            return None
    return found


def _replace(document: Any, path: str, value: Any) -> None:
    parent_path, _, key = path.rpartition(".")
    parent = _at(document, parent_path) if parent_path else document
    if isinstance(parent, dict) and key in parent:
        parent[key] = value
    elif isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
        parent[int(key)] = value
    else:
        raise Invalid(f"Nothing at {path!r} to replace")


def _url(source: DataSource, options: HttpOptions) -> httpx.URL:
    if not source.address.startswith(("http://", "https://")):
        raise Invalid(f"The address of source {source.name} is not an http(s) URL")
    try:
        # Merged here because httpx's `params` would replace the query the address has.
        return httpx.URL(source.address).copy_merge_params(options.params)
    except httpx.InvalidURL as error:
        raise Invalid(f"The address of source {source.name} is not a URL: {error}") from None


async def _check_public(url: httpx.URL) -> None:
    """Refuses a host that is not public before anything is sent to it. The address
    connected to is checked again by _PublicNetwork."""
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        await _public_addresses(url.host, port)
    except OSError as error:
        raise SourceUnavailable(f"{url.host} could not be resolved: {error}") from None


async def _public_addresses(host: str, port: int) -> list[str]:
    """The addresses the host resolves to. Raises Invalid unless every one is public: not
    loopback, private, link-local (cloud metadata services), multicast or unspecified."""
    found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = []
    for *_, address in found:
        ip = ipaddress.ip_address(address[0])
        if ip.is_multicast or not ip.is_global:
            raise Invalid(
                f"{host} is not a public address ({ip}); sources read public addresses only"
            )
        addresses.append(str(ip))
    return list(dict.fromkeys(addresses))


class _PublicNetwork(httpcore.AsyncNetworkBackend):
    """Connects only to public addresses: it resolves the host itself and connects to the
    addresses it checked, so a name that is public when checked and private a moment
    later (DNS rebinding) cannot reach the platform's network. TLS still verifies the
    host's name, which httpcore passes to start_tls, and the Host header is unchanged."""

    def __init__(self) -> None:
        self.network = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's signature)
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            async with asyncio.timeout(timeout):
                addresses = await _public_addresses(host, port)
        except TimeoutError:
            raise httpcore.ConnectTimeout(f"{host} was not resolved in time") from None
        except OSError as error:
            raise httpcore.ConnectError(f"{host} could not be resolved: {error}") from None
        connect = functools.partial(
            self.network.connect_tcp,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        # Each in turn, as a client given the name would try them.
        for address in addresses[:-1]:
            with contextlib.suppress(httpcore.ConnectError, httpcore.ConnectTimeout):
                return await connect(address)
        return await connect(addresses[-1])

    async def sleep(self, seconds: float) -> None:
        await self.network.sleep(seconds)


def _public_transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport()
    # httpx 0.28 takes no network backend, but the httpcore pool it builds does; set
    # there, the pool keeps httpx's TLS settings and limits.
    transport._pool._network_backend = _PublicNetwork()
    return transport
