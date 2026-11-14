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

Time ranges. The readers send what the options say and nothing more. A source that can be
asked for some periods only declares `pushdown` in its options, and the source service
writes the requested periods into `params` or `body` before it calls the reader
(ada.core.services.sources.pushdown), so the reader needs no notion of periods.
"""

import hashlib
import json
from typing import Any, Literal

import httpx
from pydantic import Field, ValidationError

from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.sources import AccessKind, DataSource
from ada.core.models.time import TimeRange
from ada.core.ports.sources import SourceReader, SourceReaders
from ada.core.ports.system import Clock

# Names us to the services we read, as their terms usually ask.
USER_AGENT = "ADA/0.1 (traceable data analysis; +https://github.com/benni-tec/ada)"
HTTP_KINDS = (AccessKind.URL, AccessKind.REQUEST)
# Statistics APIs can take a while to assemble a table, but not minutes.
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

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

    def __init__(self, client: httpx.AsyncClient, clock: Clock, kind: AccessKind) -> None:
        if kind not in (AccessKind.URL, AccessKind.REQUEST):
            raise ValueError(f"HTTP reads URL and request sources, not {kind.value}")
        self.client = client
        self.clock = clock
        self.kind = kind

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
        """Send one request. Raises SourceUnavailable when it fails, and when the answer is
        an error unless `ok` is False."""
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            reason = str(error) or type(error).__name__
            raise SourceUnavailable(f"{method} {url} failed: {reason}") from error
        if ok and response.is_error:
            raise SourceUnavailable(
                f"{method} {url} answered {response.status_code} {response.reason_phrase}"
            )
        return response


class HttpSourceReaders(SourceReaders):
    """The installed readers. Browser and document sources come later."""

    def __init__(self, client: httpx.AsyncClient, clock: Clock) -> None:
        self.readers = {kind: HttpReader(client, clock, kind) for kind in HTTP_KINDS}

    def for_kind(self, kind: AccessKind) -> SourceReader:
        try:
            return self.readers[kind]
        except KeyError:
            raise Invalid(f"Reading {kind.value} sources is not installed yet") from None


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
