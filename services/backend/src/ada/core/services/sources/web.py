"""The rules of web sources (`access_kind: "web"`, `format: "html"`): which options each
operation takes, the shortest freshness it may have, and when a forced refresh is refused.
Reading them is ada.adapters.sources.web; watching their pages is DataSources.watch."""

from datetime import datetime, timedelta

from ada.core.models.errors import Invalid
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    DOCUMENT_COLUMNS,
    MODEL_EXTRACTED,
    WEB_CRAWL_MAX_PAGES,
    WEB_MINIMUM_TTL,
    WEB_PDF_OPERATIONS,
    WEB_PROVENANCE_COLUMNS,
    WEB_SOURCES_COLUMN,
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    WebOperation,
    document_extract,
    web_operation,
    web_pdf,
)
from ada.core.models.web import render_wait

# The columns an extraction may fill.
MAX_EXTRACT_COLUMNS = 30


def web_schema(options: dict[str, object], declared: Schema | None) -> Schema:
    schema = _web_schema(options, declared)
    if options.get("include_provenance") is True:
        names = {column.name for column in WEB_PROVENANCE_COLUMNS}
        columns = tuple(column for column in schema.columns if column.name.casefold() not in names)
        return schema.model_copy(update={"columns": (*columns, *WEB_PROVENANCE_COLUMNS)})
    return schema


def _web_schema(options: dict[str, object], declared: Schema | None) -> Schema:
    """A web source's declared schema at registration: the document columns of its
    extract mode for scrape and crawl; for answers and extract the declared columns, which
    it must have, for answers with `sources` added at the end."""
    operation = web_operation(options)
    if operation not in MODEL_EXTRACTED:
        columns = DOCUMENT_COLUMNS[document_extract(options)]
        if declared is None:
            return Schema(columns=columns)
        return declared if declared.columns else declared.model_copy(update={"columns": columns})
    if declared is None or not declared.columns:
        raise Invalid(
            f'A web source with operation "{operation.value}" needs a declared schema with '
            "the columns of its rows"
        )
    if operation is WebOperation.EXTRACT:
        return declared
    if any(column.name == WEB_SOURCES_COLUMN.name for column in declared.columns):
        return declared
    return declared.model_copy(update={"columns": (*declared.columns, WEB_SOURCES_COLUMN)})


def check_web(source: DataSource) -> None:
    """Raises Invalid for a web source that cannot work, or would spend credits too often."""
    is_web = source.access_kind is AccessKind.WEB
    if is_web != (source.format is DataFormat.HTML):
        raise Invalid('A web source has the format "html", and only a web source has')
    if not is_web:
        return
    if not source.address.startswith(("http://", "https://")):
        raise Invalid("The address of a web source is an http(s) URL")
    operation = web_operation(source.options)
    _check_freshness(source, operation)
    options = source.options
    if "original_html" in options and type(options["original_html"]) is not bool:
        raise Invalid("options.original_html must be true or false")
    if options.get("original_html") and (
        operation is not WebOperation.SCRAPE
        or document_extract(options).value != "tables"
        or options.get("pdf") is not None
        or options.get("wait_for") is not None
    ):
        raise Invalid(
            "options.original_html requires scrape with extract=tables, without pdf or wait_for"
        )
    render_wait(options.get("wait_for"))
    if "include_provenance" in options and type(options["include_provenance"]) is not bool:
        raise Invalid("options.include_provenance must be true or false")
    if options.get("include_provenance") and operation not in WEB_PDF_OPERATIONS:
        raise Invalid("options.include_provenance is supported by scrape and extract only")
    if "wait_for" in options and operation not in WEB_PDF_OPERATIONS:
        raise Invalid("options.wait_for is supported by scrape and extract only")
    if web_pdf(options) is not None and operation not in WEB_PDF_OPERATIONS:
        raise Invalid(
            f'options.pdf is for the operations "scrape" and "extract", not "{operation.value}"'
        )
    if operation is WebOperation.ANSWERS:
        _check_answers(source)
        return
    if operation is WebOperation.EXTRACT:
        _check_extract(source)
        return
    extract = document_extract(options)
    expected = [column.name for column in DOCUMENT_COLUMNS[extract]]
    if options.get("include_provenance"):
        expected.extend(column.name for column in WEB_PROVENANCE_COLUMNS)
    declared = source.declared_schema
    if declared is None or [column.name for column in declared.columns] != expected:
        raise Invalid(
            f'A web source with extract "{extract.value}" has the columns '
            f"{', '.join(expected)}; to extract something else, register another source"
        )
    if operation is WebOperation.CRAWL:
        max_pages = options.get("max_pages", 10)
        if not isinstance(max_pages, int) or not 1 <= max_pages <= WEB_CRAWL_MAX_PAGES:
            raise Invalid(f"options.max_pages of a crawl is between 1 and {WEB_CRAWL_MAX_PAGES}")
        max_depth = options.get("max_depth")
        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 0):
            raise Invalid("options.max_depth of a crawl is 0 or more")
        for name in ("url_regex", "exclude_url_regex"):
            value = options.get(name)
            if value is not None and (not isinstance(value, str) or len(value) > 256):
                raise Invalid(
                    f"options.{name} of a crawl is a regular expression of up to 256 characters"
                )


def check_forced_refresh(source: DataSource, current: Snapshot | None, now: datetime) -> None:
    """A crawl, answers or extract source is fetched at most once within its minimum ttl,
    forced or not, so no one burns its credits by forcing refreshes. A watched source is
    refreshed whenever its monitor fires (Context.dev checks the page once a day)."""
    if source.access_kind is not AccessKind.WEB or current is None:
        return
    # A watched page is refetched when its monitor saw it change, at most daily.
    if source.monitor_id is not None:
        return
    operation = web_operation(source.options)
    if operation is WebOperation.SCRAPE:
        return
    # The last fetch that succeeded: the last check unless it failed, else the snapshot's.
    fetched = (
        source.last_checked_at
        if source.last_checked_at is not None and source.last_error is None
        else current.fetched_at
    )
    possible = fetched + timedelta(seconds=WEB_MINIMUM_TTL[operation])
    if now < possible:
        raise Invalid(
            f"{source.name} was fetched on {fetched:%Y-%m-%d %H:%M} UTC; a web source with "
            f'operation "{operation.value}" is fetched at most every '
            f"{_days(WEB_MINIMUM_TTL[operation])} days, so it can be refreshed again from "
            f"{possible:%Y-%m-%d %H:%M} UTC"
        )


def _check_freshness(source: DataSource, operation: WebOperation) -> None:
    policy = source.freshness
    minimum = WEB_MINIMUM_TTL[operation]
    if policy.kind not in (FreshnessKind.TTL, FreshnessKind.MANUAL, FreshnessKind.PUSH):
        raise Invalid(
            f'A web source is kept fresh by "ttl" (at least {_days(minimum)} days for '
            f'operation "{operation.value}"), "manual", or "push" when its page is watched '
            f'(watch_source), not "{policy.kind.value}"'
        )
    if policy.kind is FreshnessKind.TTL and (policy.ttl_seconds or 0) < minimum:
        raise Invalid(
            f'A web source with operation "{operation.value}" has a ttl of at least '
            f"{_days(minimum)} days (ttl_seconds {minimum} or more), so its credits are "
            "spent rarely"
        )


def _check_answers(source: DataSource) -> None:
    task = source.options.get("task")
    if not isinstance(task, str) or not task.strip() or len(task) > 2000:
        raise Invalid(
            'options.task of an "answers" source is the research task, 1 to 2000 characters'
        )
    example = source.options.get("json_format")
    arrays = (
        [value for value in example.values() if isinstance(value, list)]
        if isinstance(example, dict)
        else []
    )
    if len(arrays) != 1 or not arrays[0] or not isinstance(arrays[0][0], dict):
        raise Invalid(
            'options.json_format of an "answers" source is an example object whose top '
            'level has one array of records, e.g. {"rows": [{"country": "FI", "value": 1.5}]}'
        )
    declared = source.declared_schema
    names = [column.name for column in declared.columns] if declared else []
    if not names or names[-1] != WEB_SOURCES_COLUMN.name:
        raise Invalid(
            'A web source with operation "answers" declares the columns of its records, '
            'and ends with the column "sources"'
        )


def _check_extract(source: DataSource) -> None:
    instruction = source.options.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
        raise Invalid(
            'options.instruction of an "extract" source says which rows to read off the '
            "page, 1 to 2000 characters"
        )
    declared = source.declared_schema
    reserved = (
        {column.name for column in WEB_PROVENANCE_COLUMNS}
        if source.options.get("include_provenance")
        else set()
    )
    columns = (
        [column for column in declared.columns if column.name.casefold() not in reserved]
        if declared
        else []
    )
    if not 1 <= len(columns) <= MAX_EXTRACT_COLUMNS:
        raise Invalid(
            f'A web source with operation "extract" declares 1 to {MAX_EXTRACT_COLUMNS} '
            "columns, which the extraction fills"
        )


def _days(seconds: int) -> int:
    return seconds // (24 * 60 * 60)
