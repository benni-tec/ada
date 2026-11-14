from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Schema
from ada.core.models.sources import AccessKind, DataFormat, DataSource, FreshnessPolicy
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.mcp.injection import Inject


class RefreshQueued(DomainModel):
    data_source_id: Id
    force: bool
    status: str = "queued"


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def register_source(
        project_id: Id,
        name: str,
        address: str,
        projects: FromDishka[ProjectService],
        service: FromDishka[SourceService],
        format: DataFormat = DataFormat.CSV,
        access_kind: AccessKind = AccessKind.URL,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        """Register a data source in a project, once, so that pipelines can read it. Use it
        for a stable URL that returns CSV, JSON or Parquet (access_kind "url"), or one HTTP
        request with method, headers and body in `options` (access_kind "request").
        For a PDF URL use access_kind "document" with format "pdf": `options.extract`
        "pages" (default) gives rows `page, text`, "tables" gives `page, "table", row,
        cells` (a list of strings); the columns are declared for you. `freshness` says
        when the data counts as outdated; without it the source is only refreshed on
        request. `declared_schema` states column types and what columns mean,
        which the platform cannot work out by itself.

        Registering does not fetch anything: call refresh_source to load the data, then
        add_source_operator to start a pipeline from it. Returns the source with its id."""
        await projects.get(project_id)
        return await service.register(
            project_id,
            name,
            access_kind,
            address,
            format,
            options=options,
            freshness=freshness,
            declared_schema=declared_schema,
        )

    @mcp.tool
    @inject
    async def list_sources(
        project_id: Id,
        projects: FromDishka[ProjectService],
        service: FromDishka[SourceService],
    ) -> Sequence[DataSource]:
        """List a project's registered data sources. Use it to find a source before
        registering a duplicate. Each entry shows the address, freshness policy, when it
        was last checked and `last_error`, which is set while its last refresh is failing
        (widgets on it then show stale data)."""
        await projects.get(project_id)
        return await service.list(project_id)

    @mcp.tool
    @inject
    async def update_source(
        source_id: Id,
        expected_revision: int,
        service: FromDishka[SourceService],
        dispatcher: FromDishka[TaskDispatcher],
        after_commit: FromDishka[AfterCommit],
        name: str | None = None,
        address: str | None = None,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        """Correct a registered data source, e.g. a wrong address or options. Pass the
        `revision` you last read as `expected_revision`; if someone changed the source
        since, this fails and you read it again. Fields left out stay as they are.

        A changed address or options queues a forced refresh in the background, so its
        data comes from the new request. Operators already built on the source keep their
        ids. Returns the source with its new revision."""
        before = await service.get(source_id)
        updated = await service.update(
            source_id,
            expected_revision,
            name=name,
            address=address,
            options=options,
            freshness=freshness,
            declared_schema=declared_schema,
        )
        if (before.address, before.options) != (updated.address, updated.options):
            # Queued after the commit: the worker must read the new address, not the old.
            after_commit.add(lambda: dispatcher.refresh_source(source_id, True))
        return updated

    @mcp.tool
    @inject
    async def refresh_source(
        source_id: Id,
        service: FromDishka[SourceService],
        dispatcher: FromDishka[TaskDispatcher],
        force: bool = False,
    ) -> RefreshQueued:
        """Fetch a data source's data in the background and store it as a snapshot. Use it
        after register_source and whenever the data may have changed. It returns at once;
        the fetch runs in the worker. A source whose data did not change gets no new
        snapshot. `force` skips the freshness check and the cheap probe for change."""
        await service.get(source_id)
        await dispatcher.refresh_source(source_id, force)
        return RefreshQueued(data_source_id=source_id, force=force)
