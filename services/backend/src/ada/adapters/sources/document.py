"""Reading document sources: a web page, or the table a model extracts from it, through
Context.dev (ada.core.ports.web.PageReader).

Keys of `DataSource.options`:

`extract`
    {"instruction": str, "columns": [str, ...]}: what rows to read out of the page. The
    answer is a JSON array of objects with exactly these columns. Without it the answer is
    one row {"url", "title", "text"} holding the page's text.
"""

import json
from collections.abc import Sequence

from pydantic import Field, ValidationError

from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.sources import DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.ports.sources import SourceReader
from ada.core.ports.system import Clock
from ada.core.ports.web import PageReader


class Extract(DomainModel):
    instruction: str = Field(min_length=1)
    columns: Sequence[str] = Field(min_length=1)


class DocumentOptions(DomainModel):
    extract: Extract | None = None


class DocumentReader(SourceReader):
    def __init__(self, pages: PageReader, clock: Clock) -> None:
        self.pages = pages
        self.clock = clock

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        if source.format is not DataFormat.JSON:
            raise Invalid("A document source has format json")
        try:
            options = DocumentOptions.model_validate(
                {k: v for k, v in source.options.items() if k == "extract"}
            )
        except ValidationError as error:
            raise Invalid(f"Invalid options for source {source.name}: {error}") from None
        rows: Sequence[JsonObject]
        if options.extract is None:
            page = await self.pages.read(source.address)
            rows = [{"url": page.url, "title": page.title, "text": page.text}]
        else:
            rows = await self.pages.extract(
                source.address, options.extract.instruction, options.extract.columns
            )
        return FetchedData(
            content=json.dumps(rows).encode(),
            format=DataFormat.JSON,
            fetched_at=self.clock.now(),
            origin=source.address,
        )

    async def probe(self, source: DataSource) -> str | None:
        return None
