import asyncio

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.ports.repositories import SnapshotRepository
from ada.core.services.ports.refreshes import (
    MAX_WAIT_SECONDS,
    RefreshOutcome,
    RefreshService,
    RefreshStatus,
    SnapshotSummary,
)
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import WHOLE_SOURCE, source_operator_id


class WaitingRefreshes(RefreshService):
    """A refresh for a caller that waits for it, e.g. an agent that wants to look at the
    data next. The refresh is the source service's own; a failure is recorded and
    announced by it as for the worker, and reported here instead of raised, so the
    caller's unit of work commits what was recorded."""

    def __init__(self, sources: SourceService, snapshots: SnapshotRepository) -> None:
        self.sources = sources
        self.snapshots = snapshots

    async def refresh_now(
        self, id: Id, force: bool = False, timeout_seconds: int = 30
    ) -> RefreshOutcome:
        if not 1 <= timeout_seconds <= MAX_WAIT_SECONDS:
            raise Invalid(f"Wait between 1 and {MAX_WAIT_SECONDS} seconds")
        source = await self.sources.get(id)
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await self.sources.refresh(id, force)
        except TimeoutError:
            # Stopped mid-fetch: nothing is read from the request any more.
            return RefreshOutcome(
                data_source_id=id,
                status=RefreshStatus.FAILED,
                error=(
                    f"The fetch took longer than {timeout_seconds} s and was stopped; refresh "
                    "without waiting to fetch it in the background"
                ),
            )
        except Exception as error:
            status, message = RefreshStatus.FAILED, str(error) or type(error).__name__
        else:
            status = RefreshStatus.FETCHED if result.changed else RefreshStatus.UNCHANGED
            message = None
        current = await self.snapshots.current(source_operator_id(source), WHOLE_SOURCE)
        summary = (
            SnapshotSummary(
                id=current.id, row_count=current.row_count, fetched_at=current.fetched_at
            )
            if current is not None
            else None
        )
        return RefreshOutcome(data_source_id=id, status=status, snapshot=summary, error=message)
