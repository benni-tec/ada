from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessPolicy,
    Provenance,
)
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.agents import ResearchService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.refreshes import MAX_WAIT_SECONDS, RefreshService, SnapshotSummary
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId


class Refreshed(DomainModel):
    data_source_id: Id
    force: bool
    # "queued" without waiting; else "fetched", "unchanged" or "failed".
    status: str = "queued"
    # When waited for: the source's current snapshot afterwards, and why it failed.
    snapshot: SnapshotSummary | None = None
    error: str | None = None


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def register_source(
        project_id: Id,
        session_id: SessionId,
        name: str,
        address: str,
        projects: FromDishka[ProjectService],
        service: FromDishka[SourceService],
        format: DataFormat = DataFormat.CSV,
        access_kind: AccessKind = AccessKind.URL,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
        provenance: Provenance | None = None,
    ) -> DataSource:
        """Register a data source in a project, once, so that pipelines can read it. Use it
        for a stable URL that returns CSV, JSON or Parquet (access_kind "url"), or one HTTP
        request with method, headers and body in `options` (access_kind "request").
        For a PDF URL use access_kind "document" with format "pdf": `options.extract`
        "pages" (default) gives rows `page, text`, "tables" gives `page, "table", row,
        cells` (a list of strings); the columns are declared for you. For a web page use
        access_kind "web" with format "html": read as Markdown through Context.dev, with
        the same `extract` and columns; `options.operation` "scrape" (default, one page,
        ttl at least 1 day), "crawl" (a site from the address on, `max_pages` up to 50, ttl
        at least 7 days), "extract" (`instruction`: which rows a model reads off the page;
        you declare the columns it fills; model-extracted; ttl at least 7 days) or "answers"
        (`task` and `json_format`, an example object with one array of records; you declare
        the columns; model-extracted rows plus `sources`; ttl at least 30 days); freshness
        "ttl", "manual", or "push" once watch_source watches the page; a forced refresh of a
        crawl, extract or answers source within its minimum is refused unless it is
        watched. `freshness` says when the data counts as outdated; without it the source
        is only refreshed on request. `declared_schema` states column types and what
        columns mean, which the platform cannot work out by itself. Fill `provenance` with
        the publisher, the licence ("unknown", with the reason in `note`, when it cannot be
        established), the landing page and `found_by` (the web search and scope that led
        to it); model-extracted operations set `extracted_by_model` themselves.

        Registering does not fetch anything: call refresh_source to load the data (with
        `wait` to have it at once), then add_source_operator to start a pipeline from it,
        or do all of it in one `build_pipeline` call. Returns the source with its id."""
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
            provenance=provenance,
        )

    @mcp.tool
    @inject
    async def list_sources(
        project_id: Id,
        session_id: SessionId,
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
        session_id: SessionId,
        source_id: Id,
        expected_revision: int,
        service: FromDishka[SourceService],
        dispatcher: FromDishka[TaskDispatcher],
        after_commit: FromDishka[AfterCommit],
        research: FromDishka[ResearchService],
        name: str | None = None,
        address: str | None = None,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
        provenance: Provenance | None = None,
    ) -> DataSource:
        """Correct a registered data source, e.g. a wrong address or options, or fill in
        its provenance (replaced whole). Pass the
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
            provenance=provenance,
        )
        if (before.address, before.options) != (updated.address, updated.options):
            await research.use_source_read(updated)
            # Queued after the commit: the worker must read the new address, not the old.
            after_commit.add(lambda: dispatcher.refresh_source(source_id, True))
        return updated

    @mcp.tool
    @inject
    async def refresh_source(
        session_id: SessionId,
        source_id: Id,
        service: FromDishka[SourceService],
        dispatcher: FromDishka[TaskDispatcher],
        refreshes: FromDishka[RefreshService],
        research: FromDishka[ResearchService],
        force: bool = False,
        wait: bool = False,
        timeout_seconds: Annotated[int, Field(ge=1, le=MAX_WAIT_SECONDS)] = 30,
    ) -> Refreshed:
        """Fetch a data source's data and store it as a snapshot. Use it after
        register_source and whenever the data may have changed. A source whose data did
        not change gets no new snapshot. `force` skips the freshness check and the cheap
        probe for change.

        Without `wait` it returns at once (status "queued") and the fetch runs in the
        worker. With `wait` the fetch runs in this call, for at most `timeout_seconds`
        (up to 60), and the answer says how it went: status "fetched", "unchanged" or
        "failed", the source's current `snapshot` (id, row count, when fetched) and the
        `error` if it failed. Wait when your next step reads the data. In a research
        session, reading a web source or a document Context.dev parses counts as a web
        call."""
        if not wait:
            # Read by the worker, outside the research turn: counted here.
            await research.use_source_read(await service.get(source_id))
            await dispatcher.refresh_source(source_id, force)
            return Refreshed(data_source_id=source_id, force=force)
        outcome = await refreshes.refresh_now(source_id, force, timeout_seconds)
        return Refreshed(
            data_source_id=source_id,
            force=force,
            status=outcome.status.value,
            snapshot=outcome.snapshot,
            error=outcome.error,
        )
