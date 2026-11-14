"""The rules of web sources (`access_kind: "web"`, `format: "html"`): which options each
operation takes, the shortest freshness it may have, and when a forced refresh is refused.
Reading them is ada.adapters.sources.web."""

from datetime import datetime, timedelta

from ada.core.models.errors import Invalid
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    DOCUMENT_COLUMNS,
    WEB_CRAWL_MAX_PAGES,
    WEB_MINIMUM_TTL,
    WEB_SOURCES_COLUMN,
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    WebOperation,
    document_extract,
    web_operation,
)


def web_schema(options: dict[str, object], declared: Schema | None) -> Schema:
    """A web source's declared schema at registration: the document columns of its
    extract mode for scrape and crawl; for answers the declared columns, which it must
    have, with `sources` added at the end."""
    if web_operation(options) is not WebOperation.ANSWERS:
        columns = DOCUMENT_COLUMNS[document_extract(options)]
        if declared is None:
            return Schema(columns=columns)
        return declared if declared.columns else declared.model_copy(update={"columns": columns})
    if declared is None or not declared.columns:
        raise Invalid(
            'A web source with operation "answers" needs a declared schema with the columns '
            "of its records"
        )
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
    if operation is WebOperation.ANSWERS:
        _check_answers(source)
        return
    extract = document_extract(options)
    expected = [column.name for column in DOCUMENT_COLUMNS[extract]]
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
    """A crawl or answers source is fetched at most once within its minimum ttl, forced or
    not, so no one burns its credits by forcing refreshes."""
    if source.access_kind is not AccessKind.WEB or current is None:
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
    if policy.kind not in (FreshnessKind.TTL, FreshnessKind.MANUAL):
        raise Invalid(
            f'A web source is kept fresh by "ttl" (at least {_days(minimum)} days for '
            f'operation "{operation.value}") or "manual", not "{policy.kind.value}"'
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


def _days(seconds: int) -> int:
    return seconds // (24 * 60 * 60)
