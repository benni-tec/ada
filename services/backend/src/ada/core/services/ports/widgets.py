from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import Widget, WidgetData


class WidgetService(Protocol):
    async def create(
        self,
        project_id: Id,
        operator_id: OperatorId,
        type: str,
        title: str,
        actor: Actor,
        spec: JsonObject | None = None,
        note: str = "",
        session_id: Id | None = None,
        inputs: dict[str, OperatorId] | None = None,
    ) -> Widget:
        """A widget on an operator's output, and on further named `inputs` if given (each an
        operator of the project; see Widget.inputs). It is created from an operator id only; no
        data passes through the caller. With a session id it is also recorded there."""
        ...

    async def update(
        self,
        id: Id,
        title: str | None = None,
        note: str | None = None,
        type: str | None = None,
        spec: JsonObject | None = None,
        inputs: dict[str, OperatorId] | None = None,
    ) -> Widget:
        """Change a widget in place; what is left out stays. New `inputs` replace the old
        ones whole. A new spec replaces the old
        one whole and is checked against the operator like a new widget's. Copies on
        dashboards are widgets of their own and do not change with it."""
        ...

    async def get(self, id: Id) -> Widget: ...
    async def list(self, project_id: Id) -> Sequence[Widget]: ...
    async def list_by_session(self, session_id: Id) -> Sequence[Widget]: ...

    async def data(
        self, id: Id, run_id: Id | None = None, limit: int = 1000, input: str = "main"
    ) -> WidgetData:
        """What the widget shows: one input's output ("main": its own operator) in the given
        run. Without a run id
        a new run with no bindings and an open time range is started."""
        ...
