from datetime import datetime
from typing import Protocol

from ada.core.models.analysis import FetchedData
from ada.core.models.base import Id
from ada.core.models.sources import AccessKind, DataSource, StoredFile
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


class FileStore(Protocol):
    """Files uploaded to ADA, for sources that read a file nobody hosts. Stored once per
    content, so uploading the same file again gives the same address."""

    async def put(self, project_id: Id, content: bytes, suffix: str) -> StoredFile: ...

    async def get(self, address: str) -> bytes:
        """The file at an upload:// address. Raises NotFound when there is none."""
        ...


class SourceLocks(Protocol):
    """Keeps two units of work from fetching the same data source at once."""

    async def hold(self, id: Id) -> None:
        """Wait until no other unit of work holds the source, then hold it until the
        caller's transaction ends. Two runs that both find a period missing would both
        store it, and the second could not: one snapshot per operator and key is current.
        After this returns, the caller reads again what it decided on, since the other
        unit of work may have stored it meanwhile."""
        ...


class SourceCheckLog(Protocol):
    """Where failed refreshes are recorded, apart from the caller's transaction."""

    async def record_failure(
        self, id: Id, at: datetime, probe_token: str | None, error: str
    ) -> None:
        """Store the outcome on the data source as DataSourceRepository.record_check does,
        in a transaction of its own that has committed when this returns. The caller's
        transaction may still roll back, since the error is raised on to it; the record
        must stay, so the source shows the error and its widgets show stale data."""
        ...
