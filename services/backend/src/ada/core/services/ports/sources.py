from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ada.core.models.base import Id, JsonObject
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessPolicy,
    Provenance,
    RefreshResult,
)
from ada.core.models.time import TimeRange


class SourceService(Protocol):
    async def register(
        self,
        project_id: Id,
        name: str,
        access_kind: AccessKind,
        address: str,
        format: DataFormat,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
        provenance: Provenance | None = None,
    ) -> DataSource: ...

    async def get(self, id: Id) -> DataSource: ...
    async def list(self, project_id: Id) -> Sequence[DataSource]: ...

    async def update(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        address: str | None = None,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
        provenance: Provenance | None = None,
    ) -> DataSource:
        """Change the given fields; None leaves a field as it is. A model-extracted web
        operation keeps `provenance.extracted_by_model` set."""
        ...

    async def refresh(self, id: Id, force: bool = False) -> RefreshResult:
        """Bring the source's snapshots up to date: probe where the policy allows, fetch
        when something may be new, and write a snapshot only when the content changed.
        `force` skips the freshness check and the probe. When the fetch fails the old
        snapshots stay current and the error is raised."""
        ...

    async def due(self) -> Sequence[DataSource]:
        """The sources whose freshness policy says they should be refreshed now."""
        ...

    async def refresh_range(self, id: Id, time_range: TimeRange) -> Snapshot | None:
        """The source's data for a time range, as one snapshot of its source operator: the
        union of its period snapshots, after fetching the requested periods that are
        missing or stale by the freshness policy. Each period is stored as a snapshot of
        its own, keyed by the period, so a later range reuses it.

        None when the source cannot fetch by period (its options declare no pushdown) or
        the range cannot be split into periods (it has no start). The caller then reads
        the whole source, as `refresh` keeps it, and filters its rows by the time role.

        When fetching fails, periods stored before are served and the failure is recorded
        as `refresh` records it; a period that was never stored makes it raise."""
        # A default, so implementations from before pushdown keep working: they cannot
        # filter, and the caller falls back to the whole source.
        return None

    async def watch(self, id: Id) -> DataSource:
        """Have the page monitor service call this platform when the source's page changes,
        and set the source's freshness to push. Needs ADA_PUBLIC_URL and the master key.
        A source that is watched already gets a new monitor in place of its old one."""
        ...

    async def unwatch(self, id: Id) -> DataSource:
        """Delete the source's monitor and set its freshness back to manual."""
        ...

    async def verify_push(
        self, id: Id, raw_body: bytes, signature: str | None, now: datetime
    ) -> bool:
        """Whether a webhook delivery for the source is signed by its monitor and recent.
        False when the source has no monitor."""
        ...
