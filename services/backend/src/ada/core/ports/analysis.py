from typing import Protocol

from ada.core.models.analysis import FetchedData, Query, Rows, StoredSnapshot
from ada.core.models.base import Id
from ada.core.models.schema import Column, Schema


class AnalysisStore(Protocol):
    """Where snapshots are stored and queried. Snapshots are written once and never
    changed, and are addressed by the location the store returns."""

    async def is_usable(self) -> bool:
        """Whether queries run and the snapshot directory can be written."""
        ...

    async def write(
        self, project_id: Id, data: FetchedData, declared: Schema | None = None
    ) -> StoredSnapshot:
        """Store fetched data as a snapshot. Columns and types are read from the data; a
        declared schema adds the roles and must name only columns that exist, otherwise
        Invalid is raised. Writing identical data returns the same content hash."""
        ...

    async def materialize(self, project_id: Id, query: Query) -> StoredSnapshot:
        """Run the query and store its whole result as a snapshot."""
        ...

    async def describe(self, query: Query) -> tuple[Column, ...]:
        """The columns the query would return, without running it. Raises Invalid when
        the SQL does not parse or names something that does not exist."""
        ...

    async def run(self, query: Query, limit: int) -> Rows:
        """Run the query and return at most `limit` rows."""
        ...
