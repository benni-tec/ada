from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Schema
from ada.core.models.sources import AccessKind, DataFormat, DataSource, FreshnessPolicy
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.projects import ProjectService
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


class SourceChange(Request):
    """Fields left out stay as they are."""

    expected_revision: int
    name: str | None = None
    address: str | None = None
    options: JsonObject | None = None
    freshness: FreshnessPolicy | None = None
    declared_schema: Schema | None = None


class RefreshRequest(Request):
    # Skip the freshness check and the probe.
    force: bool = False


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
    )


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
    )
    if refetch_needed(before, updated):
        # Queued after the commit: the worker must read the new address, not the old one.
        after_commit.add(lambda: dispatcher.refresh_source(source_id, True))
    return updated


def refetch_needed(before: DataSource, after: DataSource) -> bool:
    """Whether an edit changed what a fetch of the source returns."""
    return (before.address, before.options) != (after.address, after.options)


@router.post("/sources/{source_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_source(
    source_id: Id,
    service: FromDishka[SourceService],
    dispatcher: FromDishka[TaskDispatcher],
    body: RefreshRequest | None = None,
) -> RefreshQueued:
    """Queue a refresh and answer at once; the worker reports the outcome as a
    `source.refreshed` or `source.refresh_failed` event."""
    # Read the source first, so an unknown id is a 404 and not a task that fails later.
    await service.get(source_id)
    force = body.force if body else False
    await dispatcher.refresh_source(source_id, force)
    return RefreshQueued(data_source_id=source_id, force=force)
