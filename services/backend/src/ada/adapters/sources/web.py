"""Reading web sources: pages, sites and researched answers, through Context.dev.

`options.operation` (WebOperation) says what is asked for:

`"scrape"` (the default)
    The page at the address, as Markdown, made into rows like a document read by
    Context.dev (`options.extract`: `pages`, one row `page 1, text`, or `tables`, the rows
    of its Markdown tables), with the same columns (DOCUMENT_COLUMNS). For a PDF,
    `options.pdf` (`start`, `end`, `ocr`) reads a page range, with OCR for tables that are
    images; each page then starts with a `<!-- page N -->` line in the one row's text.
`"crawl"`
    The site from the address on (`max_pages` up to 50, `max_depth`, `url_regex`,
    `exclude_url_regex`). `pages`: one row per page in the order crawled, `text` its URL
    on the first line, then its Markdown; `tables`: the Markdown tables of all pages, `page`
    being the page's number in that order.
`"answers"`
    Context.dev's researched answer to `task`, in the shape of `json_format`, whose top
    level holds one array of records: the records are the rows, in the declared columns,
    plus `sources` (the URLs the answer read or cites). Model-extracted, not read from a
    document.
`"extract"`
    The rows a model reads off the page at the address, following `instruction`, in the
    declared columns (null where the page states no value). Model-extracted. `options.pdf`
    as for scrape.

Each fetch spends the project's daily web credits first (WebBudget): its price, or for a
crawl `max_pages`, corrected afterwards to what Context.dev says it charged (a PDF read
with OCR costs a credit per page). A
refused budget is Invalid, as are Context.dev's refusals; a fetch that was sent stays
counted when it fails. There is no probe: web sources are kept fresh by ttl, or by a page
monitor that refreshes them when the page changed (push).
"""

import asyncio
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from ada.adapters.sources.context_dev import markdown_pages, markdown_tables
from ada.adapters.sources.document import document_parquet
from ada.core.models.analysis import FetchedData
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType
from ada.core.models.sources import (
    WEB_ANSWERS_CREDITS,
    WEB_CRAWL_MAX_PAGES,
    WEB_EXTRACT_CREDITS,
    WEB_SCRAPE_CREDITS,
    WEB_SOURCES_COLUMN,
    DataFormat,
    DataSource,
    DocumentExtract,
    WebOperation,
    document_extract,
    web_operation,
    web_pdf,
)
from ada.core.models.time import TimeRange
from ada.core.ports.sources import SourceReader
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer

_DUCKDB_TYPES = {
    ColumnType.TEXT: "VARCHAR",
    ColumnType.INTEGER: "BIGINT",
    ColumnType.NUMBER: "DOUBLE",
    ColumnType.BOOLEAN: "BOOLEAN",
    ColumnType.DATE: "DATE",
    ColumnType.TIMESTAMP: "TIMESTAMPTZ",
    ColumnType.JSON: "JSON",
}


class WebPageReader(SourceReader):
    def __init__(
        self, explorer: WebExplorer, budget: WebBudget, clock: Clock, daily_credit_limit: int
    ) -> None:
        self.explorer = explorer
        self.budget = budget
        self.clock = clock
        self.limit = daily_credit_limit

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        operation = web_operation(source.options)
        if not self.explorer.configured:
            # Before the budget: nothing is sent, so nothing is spent.
            raise Invalid(
                "Web sources need a Context.dev key: CONTEXT_DEV_API_KEY in the backend's "
                "environment (.env.local in development)"
            )
        tags = ("ada", f"project:{source.project_id}")
        match operation:
            case WebOperation.SCRAPE:
                await self._spend(source, WEB_SCRAPE_CREDITS)
                page = await self.explorer.read(
                    source.address, tags=tags, pdf=web_pdf(source.options)
                )
                if page.credits is not None and page.credits != WEB_SCRAPE_CREDITS:
                    await self.budget.adjust(
                        source.project_id, self._day(), page.credits - WEB_SCRAPE_CREDITS
                    )
                content = await self._document(source, page.markdown)
                origin = page.url
            case WebOperation.CRAWL:
                max_pages = int(source.options.get("max_pages", 10))
                await self._spend(source, max_pages)
                crawl = await self.explorer.crawl(
                    source.address,
                    max_pages=max_pages,
                    max_depth=source.options.get("max_depth"),
                    url_regex=source.options.get("url_regex"),
                    exclude_url_regex=source.options.get("exclude_url_regex"),
                    tags=tags,
                )
                if crawl.credits != max_pages:
                    await self.budget.adjust(
                        source.project_id, self._day(), crawl.credits - max_pages
                    )
                if not crawl.pages:
                    raise Invalid(f"Context.dev found no pages to crawl at {source.address}")
                content = await asyncio.to_thread(_crawl_parquet, source, crawl.pages)
                origin = source.address
            case WebOperation.ANSWERS:
                await self._spend(source, WEB_ANSWERS_CREDITS)
                answer = await self.explorer.answer(
                    str(source.options["task"]), source.options["json_format"], tags=tags
                )
                if answer.credits != WEB_ANSWERS_CREDITS:
                    await self.budget.adjust(
                        source.project_id, self._day(), answer.credits - WEB_ANSWERS_CREDITS
                    )
                records = answer_records(answer.content)
                content = await asyncio.to_thread(_records_parquet, source, records, answer.sources)
                origin = source.address
            case WebOperation.EXTRACT:
                assert source.declared_schema is not None
                await self._spend(source, WEB_EXTRACT_CREDITS)
                extraction = await self.explorer.extract(
                    source.address,
                    str(source.options["instruction"]),
                    [column.name for column in source.declared_schema.columns],
                    tags=tags,
                    pdf=web_pdf(source.options),
                )
                if extraction.credits != WEB_EXTRACT_CREDITS:
                    await self.budget.adjust(
                        source.project_id, self._day(), extraction.credits - WEB_EXTRACT_CREDITS
                    )
                content = await asyncio.to_thread(_records_parquet, source, extraction.rows, None)
                origin = source.address
        return FetchedData(
            content=content,
            format=DataFormat.PARQUET,
            fetched_at=self.clock.now(),
            origin=origin,
        )

    async def probe(self, source: DataSource) -> str | None:
        return None

    async def _spend(self, source: DataSource, credits: int) -> None:
        if not await self.budget.spend(source.project_id, self._day(), credits, self.limit):
            raise Invalid(
                f"The web budget of this project ({self.limit} credits a day) does not "
                f"leave the {credits} this refresh of {source.name} needs today"
            )

    def _day(self) -> date:
        return self.clock.now().date()

    async def _document(self, source: DataSource, markdown: str) -> bytes:
        extract = document_extract(source.options)
        rows: list[tuple[Any, ...]] = list(
            markdown_pages(markdown)
            if extract is DocumentExtract.PAGES
            else markdown_tables(markdown)
        )
        return await asyncio.to_thread(document_parquet, extract, rows)


def answer_records(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The records of an answer: the one array at its top level."""
    arrays = [value for value in content.values() if isinstance(value, list)]
    if len(arrays) != 1:
        raise Invalid("The answer does not hold exactly one array of records at its top level")
    return [record for record in arrays[0] if isinstance(record, dict)]


def _crawl_parquet(source: DataSource, pages: list[Any]) -> bytes:
    extract = document_extract(source.options)
    rows: list[tuple[Any, ...]] = []
    for number, page in enumerate(pages[:WEB_CRAWL_MAX_PAGES], start=1):
        if extract is DocumentExtract.PAGES:
            rows.append((number, f"{page.url}\n\n{page.markdown.strip()}"))
        else:
            # One crawled page is one page: its tables are numbered within it.
            rows.extend(
                (number, table, row, cells)
                for _, table, row, cells in markdown_tables(page.markdown)
            )
    return document_parquet(extract, rows)


def _records_parquet(
    source: DataSource, records: list[dict[str, Any]], sources: list[str] | None
) -> bytes:
    """The records in the declared columns, converted to their types (a value that does
    not convert is null), and for an answer its sources on every row."""
    assert source.declared_schema is not None
    columns: list[Column] = [
        column
        for column in source.declared_schema.columns
        if sources is None or column.name != WEB_SOURCES_COLUMN.name
    ]
    sources_column = _quote(WEB_SOURCES_COLUMN.name)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "records.parquet"
        with duckdb.connect(":memory:") as connection:
            raw = [f"{_quote(column.name)} VARCHAR" for column in columns]
            if sources is not None:
                raw.append(f"{sources_column} VARCHAR[]")
            connection.execute(f"CREATE TABLE records ({', '.join(raw)})")
            rows = [
                (
                    *(_text(record.get(column.name)) for column in columns),
                    *(() if sources is None else (sources,)),
                )
                for record in records
            ]
            if rows:
                marks = ", ".join("?" for _ in rows[0])
                connection.executemany(f"INSERT INTO records VALUES ({marks})", rows)
            typed = [
                f"TRY_CAST({name} AS {_DUCKDB_TYPES[column.type]}) AS {name}"
                for column in columns
                for name in [_quote(column.name)]
            ]
            if sources is not None:
                typed.append(sources_column)
            literal = "'" + str(path).replace("'", "''") + "'"
            connection.execute(
                f"COPY (SELECT {', '.join(typed)} FROM records) TO {literal} (FORMAT parquet)"
            )
        return path.read_bytes()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
