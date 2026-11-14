from typing import Protocol

from ada.core.models.base import Id
from ada.core.models.operators import OperatorId


class TaskDispatcher(Protocol):
    """Hands work to the background worker. Each call returns once the task is queued."""

    async def refresh_source(self, data_source_id: Id, force: bool = False) -> None: ...

    async def execute(self, run_id: Id, operator_id: OperatorId) -> None:
        """Make an operator's output available in a run, materializing what is missing."""
        ...

    async def check_alert_rule(self, rule_id: Id) -> None: ...

    async def run_turn(self, turn_id: Id) -> None:
        """Let the in-platform agent answer a message."""
        ...

    async def judge_widget(self, widget_id: Id) -> None:
        """Let the project's judge review a widget on a fresh run and store the verdict."""
        ...
