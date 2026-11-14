from typing import Protocol

from ada.core.models.analysis import FetchedData
from ada.core.models.sources import AccessKind, DataSource
from ada.core.models.time import TimeRange


class SourceReader(Protocol):
    """Reads one access kind of data source."""

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        """Fetch the data. The time range is passed on to the source where its options say
        how; a source that cannot filter returns everything."""
        ...

    async def probe(self, source: DataSource) -> str | None:
        """A cheap token that changes when the source's data changes, e.g. a last-updated
        date or an HTTP validator. None when the source offers nothing of the kind."""
        ...


class SourceReaders(Protocol):
    def for_kind(self, kind: AccessKind) -> SourceReader:
        """The reader for an access kind. Raises Invalid when none is installed."""
        ...
