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
import contextlib
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
from pydantic import Field, ValidationError

from ada.adapters.sources.context_dev import ContextDevParser
from ada.adapters.sources.document import DocumentReader
from ada.adapters.sources.web import WebPageReader
from ada.adapters.web.context_dev import ContextDevWeb
from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, Id
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.sources import UPLOAD_SCHEME, AccessKind, DataSource, StoredFile
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


class HttpOptions(DomainModel):
    headers: dict[str, str] = {}
    params: Params = {}
    method: Method | None = None
    body: dict[str, Any] | list[Any] | str | None = None
    probe: ProbeOptions | None = None


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
        files: FileStore | None = None,
    ) -> None:
        if kind not in (AccessKind.URL, AccessKind.REQUEST):
            raise ValueError(f"HTTP reads URL and request sources, not {kind.value}")
        self.client = client
        self.clock = clock
        self.kind = kind
        self.files = files
        self.allow_private = allow_private
        self.max_bytes = max_bytes

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        # The time range is already in the options where the source can take it (see the
        # module's docstring); it is not sent a second time.
        if source.address.startswith(UPLOAD_SCHEME):
            if self.kind is not AccessKind.URL or self.files is None:
                raise Invalid(
                    "Uploaded CSV, JSON and Parquet files need a URL source and file store"
                )
            if not source.address.startswith(f"{UPLOAD_SCHEME}{source.project_id}/"):
                raise Invalid("An uploaded file must belong to the source's project")
            return FetchedData(
                content=await self.files.get(source.address),
                format=source.format,
                fetched_at=self.clock.now(),
                origin=source.address,
            )
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
        if source.address.startswith(UPLOAD_SCHEME):
            return source.address
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
        # A HEAD answer has no body: its length is that of what GET would send.
        head = response.request.method == "HEAD"
        if not head and length.isdigit() and int(length) > self.max_bytes:
            raise too_large
        # Decoded here, since httpx's decoders take no limit and a few kilobytes of gzip
        # can hold gigabytes. Last applied, first undone.
        encodings = response.headers.get_list("content-encoding", split_commas=True)
        decoders = [
            _Inflate(name, self.max_bytes, too_large)
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
            kind: HttpReader(client, clock, kind, allow_private, max_bytes, files)
            for kind in HTTP_KINDS
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
