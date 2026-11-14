from datetime import datetime

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.judges import Verdict
from ada.core.models.operators import OperatorId
from ada.core.models.schema import Column, Schema

# The name of a widget's own operator among its inputs.
MAIN_INPUT = "main"


class Widget(DomainModel):
    """A display of one operator's output. It never holds data: it fetches the output of
    its operator from the server, for the run it is shown in."""

    id: Id
    project_id: Id
    # The session it was created in, if it was.
    session_id: Id | None = None
    operator_id: OperatorId
    # Which widget bundle renders it, e.g. "value", "table", "line-chart".
    type: str
    title: str
    # Settings of that widget type, e.g. which column is the x axis.
    spec: JsonObject = {}
    # The calling agent's one-line reason, shown in the card header.
    note: str = ""
    created_by: Actor
    created_at: datetime
    # The widget this one was copied from when it was pinned to a dashboard: the original,
    # which knows the session it was made in. A copy can then be changed on its own.
    copied_from: Id | None = None
    # Further operators the widget reads, by name, besides its own (`operator_id`, the input
    # named "main"): a text widget's placeholders or a custom widget's datasets. All are read
    # in the same run.
    inputs: dict[str, OperatorId] = {}
    # What went wrong the last time the widget was drawn, as its frame reported it; None
    # when it drew. Kept so the agent that wrote it can see it and fix it.
    render_error: str | None = None
    # A judge's review of a custom widget's code, kept beside it; None for the other types.
    verdict: Verdict | None = None

    def all_inputs(self) -> dict[str, OperatorId]:
        """Every input by name, its own operator first, as "main"."""
        return {MAIN_INPUT: self.operator_id, **self.inputs}


class WidgetData(DomainModel):
    """What a widget gets when it asks for its data."""

    widget_id: Id
    run_id: Id
    # Which of the widget's inputs this is ("main": its own operator).
    input: str = MAIN_INPUT
    # The operator's declared output: what the columns mean (time, measures and their
    # bounds), so a widget needs no second request for it.
    output: Schema
    columns: tuple[Column, ...]
    rows: tuple[tuple[object, ...], ...]
    # More rows exist than were returned.
    truncated: bool = False
    # The run has input bindings, so these are simulated numbers.
    is_scenario: bool = False
    # A source behind this could not be refreshed; the data is the last good snapshot.
    is_stale: bool = False
