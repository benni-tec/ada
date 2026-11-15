from collections.abc import Sequence
from pathlib import PurePath

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Response, status
from fastapi import Request as HttpRequest
from pydantic import Field

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    CheckEvery,
    DataFormat,
    DataSource,
    FreshnessPolicy,
    Provenance,
    StoredFile,
)
from ada.core.ports.sources import FileStore
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.refreshes import MAX_WAIT_SECONDS, RefreshOutcome, RefreshService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["sources"])


class NewSource(Request):
    name: str
    access_kind: AccessKind
    address: str
    format: DataFormat
    options: JsonObject | None = None
    freshness: FreshnessPolicy | None = None
    declared_schema: Schema | None = None
    provenance: Provenance | None = None


class SourceChange(Request):
    """Fields left out stay as they are."""

    expected_revision: int
    name: str | None = None
    address: str | None = None
    options: JsonObject | None = None
    freshness: FreshnessPolicy | None = None
    declared_schema: Schema | None = None
    provenance: Provenance | None = None


class RefreshRequest(Request):
    # Skip the freshness check and the probe.
    force: bool = False
    # Fetch in the request and answer how it went (200), instead of queueing (202). Both
    # default to null rather than a value, so generated clients may leave them out.
    wait: bool | None = None
    # Seconds; null means 30.
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_WAIT_SECONDS)


class RefreshQueued(DomainModel):
    data_source_id: Id
    force: bool


@router.get("/projects/{project_id}/sources")
async def list_sources(
    project_id: Id, projects: FromDishka[ProjectService], service: FromDishka[SourceService]
) -> Sequence[DataSource]:
    # Read the project first, so an unknown id is a 404 and not an empty list.
    await projects.get(project_id)
    return await service.list(project_id)


@router.post("/projects/{project_id}/sources", status_code=status.HTTP_201_CREATED)
async def register_source(
    project_id: Id,
    body: NewSource,
    projects: FromDishka[ProjectService],
    service: FromDishka[SourceService],
) -> DataSource:
    await projects.get(project_id)
    return await service.register(
        project_id,
        body.name,
        body.access_kind,
        body.address,
        body.format,
        options=body.options,
        freshness=body.freshness,
        declared_schema=body.declared_schema,
        provenance=body.provenance,
    )


# As much as Context.dev's parse API accepts.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/projects/{project_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: Id,
    request: HttpRequest,
    projects: FromDishka[ProjectService],
    files: FromDishka[FileStore],
    filename: str = "",
) -> StoredFile:
    """Upload a file nobody hosts, e.g. a PDF handed out at a meeting, as the raw request
    body. Register a source on the returned `address` (a document source for a PDF). The
    same content gives the same address; files are kept under the data directory."""
    await projects.get(project_id)
    content = await request.body()
    if not content:
        raise Invalid("The upload is empty: send the file as the request body")
    if len(content) > MAX_UPLOAD_BYTES:
        raise Invalid(f"Files up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB can be uploaded")
    return await files.put(project_id, content, PurePath(filename).suffix)


@router.get("/sources/{source_id}")
async def get_source(source_id: Id, service: FromDishka[SourceService]) -> DataSource:
    return await service.get(source_id)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: Id,
    body: SourceChange,
    service: FromDishka[SourceService],
    dispatcher: FromDishka[TaskDispatcher],
    after_commit: FromDishka[AfterCommit],
) -> DataSource:
    """Change a source. A changed address or options queues a forced refresh, so the
    snapshots come from what the source now says."""
    before = await service.get(source_id)
    updated = await service.update(
        source_id,
        body.expected_revision,
        name=body.name,
        address=body.address,
        options=body.options,
        freshness=body.freshness,
        declared_schema=body.declared_schema,
        provenance=body.provenance,
    )
    if refetch_needed(before, updated):
        # Queued after the commit: the worker must read the new address, not the old one.
        after_commit.add(lambda: dispatcher.refresh_source(source_id, True))
    return updated


def refetch_needed(before: DataSource, after: DataSource) -> bool:
    """Whether an edit changed what a fetch of the source returns."""
    return (before.address, before.options) != (after.address, after.options)


@router.post(
    "/sources/{source_id}/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_200_OK: {"model": RefreshOutcome, "description": "Waited for"}},
)
async def refresh_source(
    source_id: Id,
    response: Response,
    service: FromDishka[SourceService],
    dispatcher: FromDishka[TaskDispatcher],
    refreshes: FromDishka[RefreshService],
    body: RefreshRequest | None = None,
) -> RefreshQueued | RefreshOutcome:
    """Queue a refresh and answer at once (202); the worker reports the outcome as a
    `source.refreshed` or `source.refresh_failed` event. With `wait`, fetch in the
    request, for at most `timeout_seconds`, and answer how it went (200): `fetched`,
    `unchanged` or `failed`, with the current snapshot and the error."""
    body = body or RefreshRequest()
    if body.wait:
        response.status_code = status.HTTP_200_OK
        return await refreshes.refresh_now(source_id, body.force, body.timeout_seconds or 30)
    # Read the source first, so an unknown id is a 404 and not a task that fails later.
    await service.get(source_id)
    await dispatcher.refresh_source(source_id, body.force)
    return RefreshQueued(data_source_id=source_id, force=body.force)


@router.post("/sources/{source_id}/watch")
async def watch_source(
    source_id: Id, service: FromDishka[SourceService], check_every: CheckEvery | None = None
) -> DataSource:
    """Have Context.dev watch the source's page and refresh the source when it changes."""
    return await service.watch(source_id, check_every)


@router.delete("/sources/{source_id}/watch")
async def unwatch_source(source_id: Id, service: FromDishka[SourceService]) -> DataSource:
    """Stop watching the source's page; it is refreshed by hand again."""
    return await service.unwatch(source_id)
