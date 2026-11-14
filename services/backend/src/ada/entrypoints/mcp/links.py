from ada.core.models.widgets import Widget


def widget_url(widget: Widget) -> str:
    """Where a person sees the widget in the frontend, as a path on the same host.

    A widget made in a session is shown in that session's view, scrolled to its card; one
    without a session has a page of its own.
    """
    project = f"/projects/{widget.project_id}"
    if widget.session_id is not None:
        return f"{project}/sessions/{widget.session_id}?widget={widget.id}"
    return f"{project}/widgets/{widget.id}"
