"""Reading document sources: a PDF fetched over HTTP and extracted locally with pdfplumber.

The address is the PDF's URL. It is fetched and probed exactly as a URL source is (GET,
with the `headers`, `params` and `probe` options of ada.adapters.sources.http), and the
reader hands on a table, not the PDF: `options.extract` says which (DocumentExtract).

`"pages"` (the default)
    One row per page: `page integer, text text`. A page without a text layer, such as a
    scan, has empty text.
`"tables"`
    One row per row of each table pdfplumber finds on a page: `page integer, table
    integer, row integer, cells json`, where `cells` is the row's cells as a list of
    strings (an empty cell is ""). Tables are numbered per page and rows per table, all
    from 1; the first row is usually the table's header. `table` is a reserved word in SQL,
    so a transform writes it as "table".

The table is written as Parquet with the columns' exact types, so the analysis store reads
the same columns whatever the document holds, a document without tables included. A
malformed or encrypted PDF, or an answer that is not a PDF at all, raises Invalid with a
message that says so; the source records it as its last error.
"""

import asyncio
import io
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pdfplumber

from ada.core.models.analysis import FetchedData
from ada.core.models.errors import Invalid
from ada.core.models.sources import DataFormat, DataSource, DocumentExtract, document_extract
from ada.core.models.time import TimeRange
from ada.core.ports.sources import SourceReader

# The DuckDB types of the columns in DOCUMENT_COLUMNS, in their order.
_TABLES = {
    DocumentExtract.PAGES: '"page" INTEGER NOT NULL, "text" VARCHAR NOT NULL',
    DocumentExtract.TABLES: (
        '"page" INTEGER NOT NULL, "table" INTEGER NOT NULL, "row" INTEGER NOT NULL, '
        '"cells" VARCHAR[] NOT NULL'
    ),
}


class DocumentReader(SourceReader):
    """Fetches and probes through a URL reader, then extracts the PDF into rows."""

    def __init__(self, http: SourceReader) -> None:
        self.http = http

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        extract = document_extract(source.options)
        fetched = await self.http.fetch(source, time_range)
        content = await asyncio.to_thread(extract_pdf, fetched.content, extract, fetched.origin)
        return fetched.model_copy(update={"content": content, "format": DataFormat.PARQUET})

    async def probe(self, source: DataSource) -> str | None:
        return await self.http.probe(source)


def extract_pdf(content: bytes, extract: DocumentExtract, origin: str = "the document") -> bytes:
    """The PDF's pages or tables as Parquet. Raises Invalid when it cannot be read."""
    if not content.lstrip().startswith(b"%PDF-"):
        start = content[:40].decode(errors="replace").strip()
        raise Invalid(f"{origin} is not a PDF: it starts with {start!r}")
    try:
        with pdfplumber.open(io.BytesIO(content)) as document:
            if extract is DocumentExtract.PAGES:
                rows = [
                    (number, page.extract_text() or "")
                    for number, page in enumerate(document.pages, start=1)
                ]
            else:
                rows = list(_table_rows(document.pages))
    except Exception as error:
        raise Invalid(f"{origin} {_reason(error)}") from error
    return _parquet(extract, rows)


def _table_rows(pages: list[Any]) -> Any:
    for page_number, page in enumerate(pages, start=1):
        for table_number, table in enumerate(page.extract_tables(), start=1):
            for row_number, row in enumerate(table, start=1):
                cells = [cell if cell is not None else "" for cell in row]
                yield page_number, table_number, row_number, cells


def _reason(error: Exception) -> str:
    # pdfplumber wraps pdfminer's errors; the wrapped one says what went wrong.
    cause = error.args[0] if error.args and isinstance(error.args[0], Exception) else error
    name = type(cause).__name__
    if "Password" in name or "Encrypt" in name:
        return "is an encrypted PDF that cannot be opened without a password"
    detail = str(cause) or name
    return f"is not a readable PDF: {detail}"


def _parquet(extract: DocumentExtract, rows: list[tuple[Any, ...]]) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "document.parquet"
        with duckdb.connect(":memory:") as connection:
            connection.execute(f"CREATE TABLE document ({_TABLES[extract]})")
            if rows:
                marks = ", ".join("?" for _ in rows[0])
                connection.executemany(f"INSERT INTO document VALUES ({marks})", rows)
            literal = "'" + str(path).replace("'", "''") + "'"
            connection.execute(f"COPY document TO {literal} (FORMAT parquet)")
        return path.read_bytes()
