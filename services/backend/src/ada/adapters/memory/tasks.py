from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.ports.tasks import TaskDispatcher


class RecordingTaskDispatcher(TaskDispatcher):
    """Queues nothing; remembers what it was asked to run. For tests, and as the default
    until the worker's dispatcher exists."""

    def __init__(self) -> None:
        self.refreshes: list[tuple[Id, bool]] = []
        self.executions: list[tuple[Id, OperatorId]] = []
        self.alert_checks: list[Id] = []
        self.turns: list[Id] = []

    async def refresh_source(self, data_source_id: Id, force: bool = False) -> None:
        self.refreshes.append((data_source_id, force))

    async def execute(self, run_id: Id, operator_id: OperatorId) -> None:
        self.executions.append((run_id, operator_id))

    async def check_alert_rule(self, rule_id: Id) -> None:
        self.alert_checks.append(rule_id)

    async def run_turn(self, turn_id: Id) -> None:
        self.turns.append(turn_id)
