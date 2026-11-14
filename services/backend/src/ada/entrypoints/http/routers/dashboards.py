from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Response, status

from ada.core.models.base import DomainModel, Id
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.runs import Run
from ada.core.models.sessions import Session
from ada.core.models.time import TimeRange
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["dashboards"])


class DashboardView(DomainModel):
    """A dashboard with the version it points at, which is what a client shows. The
    revision to send back with the next write is `dashboard.revision`."""

    dashboard: Dashboard
    # None until the first edit.
    version: DashboardVersion | None


class NewDashboard(Request):
    name: str


class SlotsEdit(Request):
    slots: Sequence[Slot]
    expected_revision: int


class Pin(Request):
    widget_id: Id
    slot: str
    expected_revision: int


class DashboardChange(Request):
    default_time_range: TimeRange
    expected_revision: int


class NewDashboardRun(Request):
    # Left out: the dashboard's own default range.
    time_range: TimeRange | None = None


async def _view(service: DashboardService, id: Id) -> DashboardView:
    return DashboardView(dashboard=await service.get(id), version=await service.current(id))


@router.get("/projects/{project_id}/dashboards")
async def list_dashboards(
    project_id: Id, service: FromDishka[DashboardService]
) -> Sequence[Dashboard]:
    return await service.list(project_id)


@router.post("/projects/{project_id}/dashboards", status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    project_id: Id, body: NewDashboard, service: FromDishka[DashboardService]
) -> Dashboard:
    return await service.create(project_id, body.name, WEB)


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: Id, service: FromDishka[DashboardService]) -> DashboardView:
    return await _view(service, dashboard_id)


@router.patch("/dashboards/{dashboard_id}")
async def change_dashboard(
    dashboard_id: Id, body: DashboardChange, service: FromDishka[DashboardService]
) -> DashboardView:
    """Set the range shown until a viewer changes it."""
    await service.set_default_time_range(
        dashboard_id, body.default_time_range, body.expected_revision
    )
    return await _view(service, dashboard_id)


@router.put("/dashboards/{dashboard_id}/slots")
async def edit_dashboard(
    dashboard_id: Id, body: SlotsEdit, service: FromDishka[DashboardService]
) -> DashboardView:
    """Replace the slots. Adds a version and points the dashboard at it."""
    await service.edit(dashboard_id, body.slots, body.expected_revision, WEB)
    return await _view(service, dashboard_id)


@router.post("/dashboards/{dashboard_id}/pins", status_code=status.HTTP_201_CREATED)
async def pin_widget(
    dashboard_id: Id, body: Pin, service: FromDishka[DashboardService]
) -> DashboardView:
    """Put a copy of a widget in a slot, adding the slot when there is none of that name.
    The copy's `copied_from` names the original. Adds a version."""
    await service.pin_widget(dashboard_id, body.widget_id, body.slot, body.expected_revision, WEB)
    return await _view(service, dashboard_id)


@router.get("/dashboards/{dashboard_id}/versions")
async def list_versions(
    dashboard_id: Id, service: FromDishka[DashboardService]
) -> Sequence[DashboardVersion]:
    """Every version, oldest first."""
    return await service.versions(dashboard_id)


@router.get("/dashboard-versions/{version_id}")
async def get_version(version_id: Id, service: FromDishka[DashboardService]) -> DashboardVersion:
    return await service.version(version_id)


@router.post("/dashboards/{dashboard_id}/runs", status_code=status.HTTP_201_CREATED)
async def start_dashboard_run(
    dashboard_id: Id,
    dashboards: FromDishka[DashboardService],
    runs: FromDishka[RunService],
    body: NewDashboardRun | None = None,
) -> Run:
    """The cut a viewer looks at: one run for the time range (default: the dashboard's),
    which every widget on the dashboard reads."""
    dashboard = await dashboards.get(dashboard_id)
    time_range = body.time_range if body and body.time_range else dashboard.default_time_range
    return await runs.start(dashboard.project_id, WEB, time_range)


@router.post(
    "/dashboards/{dashboard_id}/agent-session",
    responses={status.HTTP_201_CREATED: {"model": Session, "description": "Created"}},
)
async def dashboard_agent_session(
    dashboard_id: Id, response: Response, service: FromDishka[SessionService]
) -> Session:
    """The session behind the dashboard's agent panel: the newest one that started from
    the dashboard and shows it, else a new one (201)."""
    session, created = await service.dashboard_agent_session(dashboard_id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return session
