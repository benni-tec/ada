from collections.abc import Sequence
from datetime import date

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.sessions import Session
from ada.core.models.time import TimeRange
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject


class DashboardState(DomainModel):
    """A dashboard as an agent needs it: what it points at, and the revision to send back."""

    dashboard: Dashboard
    # None until the dashboard's first edit.
    version: DashboardVersion | None
    # Where a person sees it in the frontend, relative to the host serving ADA.
    url: str


class PanelState(DomainModel):
    session: Session
    # The session's page, where the dashboard sits beside the conversation.
    url: str


def dashboard_url(dashboard: Dashboard) -> str:
    return f"/projects/{dashboard.project_id}/dashboards/{dashboard.id}"


async def _state(service: DashboardService, id: Id) -> DashboardState:
    dashboard = await service.get(id)
    return DashboardState(
        dashboard=dashboard, version=await service.current(id), url=dashboard_url(dashboard)
    )


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def create_dashboard(
        project_id: Id, name: str, service: FromDishka[DashboardService]
    ) -> DashboardState:
        """Create an empty dashboard in a project: a live view of widgets that follows the
        latest data, unlike a session, which is a one-off exploration. Fill it with
        `edit_dashboard`, every widget in one call. Returns the dashboard with its id, its
        revision and its `url`: give the url to the person."""
        dashboard = await service.create(project_id, name, calling_agent())
        return await _state(service, dashboard.id)

    @mcp.tool
    @inject
    async def list_dashboards(
        project_id: Id, service: FromDishka[DashboardService]
    ) -> Sequence[Dashboard]:
        """List a project's dashboards with their ids, names, revisions and default time
        ranges. Use it to find the dashboard to pin to before creating a new one."""
        return await service.list(project_id)

    @mcp.tool
    @inject
    async def get_dashboard(
        dashboard_id: Id, service: FromDishka[DashboardService]
    ) -> DashboardState:
        """Read a dashboard: its current version with the slots (name, widget id, layout)
        and the dashboard's `revision`. Read it before every write and send the revision
        back as `expected_revision`: if a person or another agent changed the dashboard in
        the meantime the write is refused, and you read again."""
        return await _state(service, dashboard_id)

    @mcp.tool
    @inject
    async def list_dashboard_versions(
        dashboard_id: Id, service: FromDishka[DashboardService]
    ) -> Sequence[DashboardVersion]:
        """Every version of a dashboard, oldest first, with who made it and when. Each edit
        adds one; reports record the version they were made from."""
        return await service.versions(dashboard_id)

    @mcp.tool
    @inject
    async def pin_widget(
        dashboard_id: Id,
        widget_id: Id,
        slot: str,
        expected_revision: int,
        service: FromDishka[DashboardService],
        layout: JsonObject | None = None,
    ) -> DashboardState:
        """Show one widget, e.g. one you made in a session, on a dashboard; to lay out
        several at once use `edit_dashboard`, in one call. The dashboard gets
        its own copy of the widget (same operator, type, spec, title and note), so either
        can be changed later without the other; the copy names the original in
        `copied_from`. It reads the same pipeline, so make sure that pipeline's sources
        have freshness policies, or the dashboard will not stay current.

        `slot` names the place on the dashboard. A slot that exists changes its widget and
        keeps its position; a new name adds a slot after the others. `layout`
        (`{"x": 0-11, "y": row, "w": columns, "h": rows}` on a 12-column grid) places the
        slot instead. Both must be in the same project. `expected_revision` is the
        dashboard's revision from `get_dashboard`. Adds a dashboard version and returns
        the dashboard as it is now."""
        await service.pin_widget(
            dashboard_id, widget_id, slot, expected_revision, calling_agent(), layout=layout
        )
        return await _state(service, dashboard_id)

    @mcp.tool
    @inject
    async def edit_dashboard(
        dashboard_id: Id,
        slots: Sequence[Slot],
        expected_revision: int,
        service: FromDishka[DashboardService],
    ) -> DashboardState:
        """Lay out a whole dashboard in one call: replace all its slots at once, to add,
        reorder, resize or remove widgets. Prefer one call with every slot to several
        pins: each call adds one dashboard version. Start from the slots `get_dashboard`
        returned. Each slot has a unique `name`, an optional `widget_id` and an optional
        `layout` on a 12-column grid: `{"x": 0-11, "y": row, "w": columns, "h": rows}`.
        Layout keys you leave out are filled in: a card is 6 columns wide and 4 rows tall
        and goes beside the previous one, or on a new row when that is full.

        `widget_id` may be any widget of the dashboard's project, e.g. one you made in a
        session or with `build_pipeline`: a widget not yet on this dashboard is copied
        onto it (`copied_from` names the original), as `pin_widget` does.
        `expected_revision` is the dashboard's revision from `get_dashboard`."""
        await service.edit(dashboard_id, slots, expected_revision, calling_agent())
        return await _state(service, dashboard_id)

    @mcp.tool
    @inject
    async def set_dashboard_time_range(
        dashboard_id: Id,
        expected_revision: int,
        service: FromDishka[DashboardService],
        start: date | None = None,
        end: date | None = None,
    ) -> Dashboard:
        """Set the time range a dashboard shows until a viewer changes it, as ISO dates
        (e.g. "2020-01-01" to "2024-12-31", both inclusive). Leave out `start` or `end`
        for no bound on that side; leave out both for all data. It does not add a
        dashboard version. Returns the dashboard with its new revision."""
        return await service.set_default_time_range(
            dashboard_id, TimeRange(start=start, end=end), expected_revision
        )

    @mcp.tool
    @inject
    async def show_dashboard_in_session(
        session_id: Id,
        expected_revision: int,
        sessions: FromDishka[SessionService],
        dashboard_id: Id | None = None,
    ) -> PanelState:
        """Show a dashboard beside the conversation in a session, so a person sees it
        change as you edit it. `expected_revision` is the session's revision, as
        `create_session` returned it. Leave out `dashboard_id` to clear the panel. The
        dashboard must be in the session's project."""
        session = await sessions.show_dashboard(session_id, dashboard_id, expected_revision)
        return PanelState(
            session=session, url=f"/projects/{session.project_id}/sessions/{session.id}"
        )
