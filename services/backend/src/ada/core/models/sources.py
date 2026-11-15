from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.web import PdfOptions, pdf_options


class AccessKind(StrEnum):
    # A stable address that returns the data.
    URL = "url"
    # One HTTP request with a method, headers and a body.
    REQUEST = "request"
    # An automated browser session that sets options and takes an export.
    BROWSER = "browser"
    # A PDF that is fetched and parsed.
    DOCUMENT = "document"
    # A web page through Context.dev (format html): its Markdown, a table a model reads off
    # it, the pages of a site, or a researched answer (WebOperation).
    WEB = "web"


class DataFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"
    # Read by document sources only, which extract it into rows (DocumentExtract).
    PDF = "pdf"
    # Read by web sources only, which extract the page into rows like a document's.
    HTML = "html"


class DocumentExtract(StrEnum):
    """What a document or web source makes of its PDF or page: `options.extract`."""

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


class DocumentEngine(StrEnum):
    """Who turns a document source's PDF into rows: `options.engine`."""

    # Locally, in the reader's process (pdfplumber). The default.
    PDFPLUMBER = "pdfplumber"
    # Context.dev's parse API (CONTEXT_DEV_API_KEY): the PDF is sent there and comes back
    # as Markdown, whose page markers and tables become the rows. Better on complex layouts.
    CONTEXT_DEV = "context.dev"


def document_engine(options: JsonObject) -> DocumentEngine:
    """The engine a document source's options ask for; pdfplumber by default."""
    value = options.get("engine", DocumentEngine.PDFPLUMBER.value)
    try:
        return DocumentEngine(value)
    except ValueError:
        engines = ", ".join(repr(engine.value) for engine in DocumentEngine)
        raise Invalid(f"options.engine must be one of {engines}, not {value!r}") from None


class WebOperation(StrEnum):
    """What a web source asks Context.dev for: `options.operation`. The dearer ones are
    sources, never exploration tools, and are kept fresh rarely (WEB_MINIMUM_TTL)."""

    # One page as Markdown (1 credit), made into pages or tables like a document. A PDF's
    # page range and OCR: `pdf` (web_pdf).
    SCRAPE = "scrape"
    # The pages of a site, from the address on (1 credit per page): `max_pages` (at most
    # WEB_CRAWL_MAX_PAGES), `max_depth`, `url_regex`, `exclude_url_regex`.
    CRAWL = "crawl"
    # A researched answer (10 credits): `task` and `json_format`, an example object whose
    # top level has one array of records. Its records are the rows, model-extracted.
    ANSWERS = "answers"
    # A table a model reads off the page (about 5 credits): `instruction`, and the declared
    # columns, whose values it fills (null where the page states none). Model-extracted.
    # `pdf` as for scrape.
    EXTRACT = "extract"


# The operations whose rows a model wrote down rather than read: their sources' provenance
# says so (`extracted_by_model`).
MODEL_EXTRACTED = frozenset({WebOperation.ANSWERS, WebOperation.EXTRACT})


def web_operation(options: JsonObject) -> WebOperation:
    """The operation a web source's options ask for; scrape by default."""
    value = options.get("operation", WebOperation.SCRAPE.value)
    try:
        return WebOperation(value)
    except ValueError:
        operations = ", ".join(repr(operation.value) for operation in WebOperation)
        raise Invalid(f"options.operation must be one of {operations}, not {value!r}") from None


# The operations that read one page, which may be a PDF: they take `options.pdf`.
WEB_PDF_OPERATIONS = frozenset({WebOperation.SCRAPE, WebOperation.EXTRACT})


def web_pdf(options: JsonObject) -> PdfOptions | None:
    """`options.pdf` of a web source, `{"start": 25, "end": 26, "ocr": true}` (each
    optional): which pages of a PDF Context.dev reads, and whether with OCR, for tables
    that are images. None without it; Invalid when it is malformed."""
    pdf = options.get("pdf")
    if pdf is None:
        return None
    if not isinstance(pdf, dict) or not set(pdf) <= {"start", "end", "ocr"}:
        raise Invalid(
            'options.pdf is an object with "start" and "end" (page numbers from 1) and '
            '"ocr" (true to read the pages with OCR), each optional, e.g. '
            '{"start": 25, "end": 26, "ocr": true}'
        )
    return pdf_options(pdf.get("start"), pdf.get("end"), pdf.get("ocr", False))


_DAY = 24 * 60 * 60
# The shortest ttl a web source may have, per operation: their credits are spent rarely.
# A forced refresh of a crawl or answers source within it is refused as well.
WEB_MINIMUM_TTL: dict[WebOperation, int] = {
    WebOperation.SCRAPE: _DAY,
    WebOperation.CRAWL: 7 * _DAY,
    WebOperation.ANSWERS: 30 * _DAY,
    WebOperation.EXTRACT: 7 * _DAY,
}
WEB_CRAWL_MAX_PAGES = 50
# Credits per call, as Context.dev charges them; a crawl costs one per page fetched.
WEB_SCRAPE_CREDITS = 1
WEB_ANSWERS_CREDITS = 10
# Reserved for an extraction, corrected afterwards to what Context.dev charged.
WEB_EXTRACT_CREDITS = 5
# The column of an answers source with the URLs the answer cites, added to its declared
# columns.
WEB_SOURCES_COLUMN = Column(name="sources", type=ColumnType.JSON, nullable=True)


# The address of a file uploaded to ADA (POST /projects/{id}/files) instead of fetched:
# upload://<project id>/<sha256><suffix>. The content never changes, so neither does it.
UPLOAD_SCHEME = "upload://"


class StoredFile(DomainModel):
    """A file uploaded to ADA, to be read by a source at `address`."""

    address: str
    sha256: str
    size: int


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
    """How an agent came upon a source: the web search and its scope."""

    query: str
    scope: str


class Provenance(DomainModel):
    """Where a source's data comes from and on what terms. Filled by whoever registers a
    source; "unknown" in `licence`, with the reason in `note`, when it cannot be told."""

    publisher: str | None = None
    licence: str | None = None
    landing_page: str | None = None
    found_by: FoundBy | None = None
    # True when a model, not a person or a parser, read the values out of the page. Set by
    # registration for web sources whose operation is model-extracted (MODEL_EXTRACTED).
    extracted_by_model: bool = False
    note: str | None = None


class CheckEvery(StrEnum):
    TEN_MINUTES = "10min"
    HOURLY = "hourly"
    DAILY = "daily"

    @property
    def minutes(self) -> int:
        return {self.TEN_MINUTES: 10, self.HOURLY: 60, self.DAILY: 1440}[self]


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
    # None keeps the configured global interval; written with the monitor by watch.
    check_every: CheckEvery | None = None
    # The monitor that watches the source. Its secret is held only by the repository, encrypted.
    monitor_id: str | None = None
    revision: int = 1


class RefreshResult(DomainModel):
    data_source_id: Id
    # False when the source was probed or fetched and nothing was new.
    changed: bool
    # The snapshots written by this refresh.
    snapshot_ids: tuple[Id, ...] = ()
