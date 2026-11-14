from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, Schema


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
    # Read by document sources only, which extract it into rows (DocumentExtract).
    PDF = "pdf"


class DocumentExtract(StrEnum):
    """What a document source makes of its PDF: `options.extract`."""

    # One row per page: its number and its text.
    PAGES = "pages"
    # One row per row of a table found on a page, its cells as a list of strings.
    TABLES = "tables"


# The columns of each extract mode. They are fixed, so a document source's operator knows
# its columns at registration. Pages, tables and rows are numbered from 1.
DOCUMENT_COLUMNS: dict[DocumentExtract, tuple[Column, ...]] = {
    DocumentExtract.PAGES: (
        Column(name="page", type=ColumnType.INTEGER, nullable=False),
        Column(name="text", type=ColumnType.TEXT, nullable=False),
    ),
    DocumentExtract.TABLES: (
        Column(name="page", type=ColumnType.INTEGER, nullable=False),
        Column(name="table", type=ColumnType.INTEGER, nullable=False),
        Column(name="row", type=ColumnType.INTEGER, nullable=False),
        Column(name="cells", type=ColumnType.JSON, nullable=False),
    ),
}


def document_extract(options: JsonObject) -> DocumentExtract:
    """The extract mode a document source's options ask for; pages by default."""
    value = options.get("extract", DocumentExtract.PAGES.value)
    try:
        return DocumentExtract(value)
    except ValueError:
        modes = ", ".join(repr(mode.value) for mode in DocumentExtract)
        raise Invalid(f"options.extract must be one of {modes}, not {value!r}") from None


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
    created_at: datetime
    # The next three are written by refreshes, outside the revision: a refresh never
    # conflicts with an edit.
    last_checked_at: datetime | None = None
    # What the last probe returned; a different token means the data changed.
    last_probe_token: str | None = None
    # Why the last refresh failed; None after a successful one. While it is set, widgets
    # on this source show their data as stale.
    last_error: str | None = None
    revision: int = 1


class RefreshResult(DomainModel):
    data_source_id: Id
    # False when the source was probed or fetched and nothing was new.
    changed: bool
    # The snapshots written by this refresh.
    snapshot_ids: tuple[Id, ...] = ()
