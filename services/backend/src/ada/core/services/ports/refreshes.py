from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ada.core.models.base import DomainModel, Id

# The longest a caller waits for a fetch in its own request.
MAX_WAIT_SECONDS = 60


class RefreshStatus(StrEnum):
    # A new snapshot was written.
    FETCHED = "fetched"
    # Nothing new: the data was fresh by its policy, or fetched and the same.
    UNCHANGED = "unchanged"
    # The fetch failed or took too long; the last good snapshot stays current.
    FAILED = "failed"


class SnapshotSummary(DomainModel):
    id: Id
    row_count: int
    fetched_at: datetime


class RefreshOutcome(DomainModel):
    data_source_id: Id
    status: RefreshStatus
    # The source's current whole-source snapshot after the refresh, if it has one.
    snapshot: SnapshotSummary | None = None
    error: str | None = None


class RefreshService(Protocol):
    async def refresh_now(
        self, id: Id, force: bool = False, timeout_seconds: int = 30
    ) -> RefreshOutcome:
        """Refresh the source in the caller's request, as `SourceService.refresh` does,
        and say how it went instead of raising: for a caller that waits for the data.
        A fetch that takes longer than `timeout_seconds` (1 to MAX_WAIT_SECONDS) is
        stopped and reported as failed."""
        ...
