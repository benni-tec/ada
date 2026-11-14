from collections.abc import Sequence
from typing import Protocol

from ada.core.models.base import Id, JsonObject
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessPolicy,
    RefreshResult,
)


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
    ) -> DataSource:
        """Change the given fields; None leaves a field as it is."""
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
