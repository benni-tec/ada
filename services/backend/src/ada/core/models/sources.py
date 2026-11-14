from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Schema


class AccessKind(StrEnum):
    # A stable address that returns the data.
    URL = "url"
    # One HTTP request with a method, headers and a body.
    REQUEST = "request"
    # An automated browser session that sets options and takes an export.
    BROWSER = "browser"
    # A PDF or page that is fetched and parsed.
    DOCUMENT = "document"


class DataFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"


class FreshnessKind(StrEnum):
    # Refreshed only when asked.
    MANUAL = "manual"
    # A snapshot expires after ttl_seconds.
    TTL = "ttl"
    # A cheap check for change runs before a full fetch, at most every ttl_seconds.
    PROBE = "probe"
    # Something outside tells us the source changed, e.g. a monitor webhook.
    PUSH = "push"


class FreshnessPolicy(DomainModel):
    kind: FreshnessKind = FreshnessKind.MANUAL
    ttl_seconds: int | None = None
    # A shorter lifetime for the newest period, which is the one that still gets revised.
    latest_period_ttl_seconds: int | None = None


class FoundBy(DomainModel):
    """How the research agent came upon a source."""

    query: str
    scope: str


class Provenance(DomainModel):
    """Where a source's data comes from and on what terms. Filled by whoever registers a
    source; "unknown" in `licence`, with the reason in `note`, when it cannot be told."""

    publisher: str | None = None
    licence: str | None = None
    landing_page: str | None = None
    found_by: FoundBy | None = None
    # True when a model, not a person or a parser, read the values out of the page.
    extracted_by_model: bool = False
    note: str | None = None


class DataSource(DomainModel):
    """Registered once per project and referenced by source operators."""

    id: Id
    project_id: Id
    name: str
    access_kind: AccessKind
    address: str
    format: DataFormat
    # Kind-specific settings: method, headers and body for a request; the time-range
    # parameter names for pushdown; the path to the rows inside a JSON response.
    options: JsonObject = {}
    freshness: FreshnessPolicy = FreshnessPolicy()
    # Declared by whoever registers the source; sources cannot derive their roles.
    declared_schema: Schema | None = None
    provenance: Provenance | None = None
    created_at: datetime
    # The next four are written by refreshes, outside the revision: a refresh never
    # conflicts with an edit.
    last_checked_at: datetime | None = None
    # What the last probe returned; a different token means the data changed.
    last_probe_token: str | None = None
    # Why the last refresh failed; None after a successful one. While it is set, widgets
    # on this source show their data as stale.
    last_error: str | None = None
    # The monitor that watches a document source, written by watch. Its secret is never
    # part of the model: only the repository holds it, encrypted.
    monitor_id: str | None = None
    revision: int = 1


class RefreshResult(DomainModel):
    data_source_id: Id
    # False when the source was probed or fetched and nothing was new.
    changed: bool
    # The snapshots written by this refresh.
    snapshot_ids: tuple[Id, ...] = ()
