import logging

from redis.exceptions import RedisError
from taskiq import AsyncBroker
from taskiq.exceptions import SendTaskError
from taskiq.kicker import AsyncKicker
from taskiq_redis import RedisStreamBroker

from ada.core.models.base import Id
from ada.core.models.errors import Unavailable
from ada.core.models.operators import OperatorId
from ada.core.ports.tasks import TaskDispatcher

logger = logging.getLogger(__name__)

# The worker's task names (`<module>:<function>`, see ada.entrypoints.worker.registry).
# Spelled out because adapters may not import entrypoints; a test checks they match what the
# worker registers.
REFRESH_SOURCE = "ada.entrypoints.worker.tasks.sources:refresh_source"
EXECUTE = "ada.entrypoints.worker.tasks.runs:execute"
CHECK_ALERT_RULE = "ada.entrypoints.worker.tasks.alerts:check_alert_rule"
RUN_TURN = "ada.entrypoints.worker.tasks.agent:run_turn"
JUDGE_WIDGET = "ada.entrypoints.worker.tasks.judges:judge_widget"


def stream_broker(valkey_url: str) -> RedisStreamBroker:
    """A broker on the stream the worker reads. The defaults (stream and consumer group
    "taskiq") are the worker's; ada.entrypoints.worker.factory builds its broker the same
    way."""
    # Only kicks go through this broker, never a blocking read, so a socket timeout cannot
    # cut a wait short; it stops a request from hanging on an unresponsive Valkey.
    return RedisStreamBroker(valkey_url, socket_connect_timeout=2, socket_timeout=2)


class ValkeyTaskDispatcher(TaskDispatcher):
    """Queues tasks for the worker by name, so this side needs none of the worker's code.
    Arguments travel as JSON, so ids are sent as strings."""

    def __init__(self, broker: AsyncBroker) -> None:
        self.broker = broker

    async def startup(self) -> None:
        try:
            # Declares the worker's consumer group if it does not exist yet. The group starts
            # at the end of the stream, so without it, tasks queued before the worker first
            # starts would never be read.
            await self.broker.startup()
        except (RedisError, OSError) as error:
            # Valkey being down must not stop the API from starting; queueing fails until it
            # is back, and the worker declares the group itself when it starts.
            logger.warning("Could not start the task broker: %s", error)

    async def shutdown(self) -> None:
        await self.broker.shutdown()

    async def refresh_source(self, data_source_id: Id, force: bool = False) -> None:
        await self._kick(REFRESH_SOURCE, data_source_id=str(data_source_id), force=force)

    async def execute(self, run_id: Id, operator_id: OperatorId) -> None:
        await self._kick(EXECUTE, run_id=str(run_id), operator_id=operator_id)

    async def check_alert_rule(self, rule_id: Id) -> None:
        await self._kick(CHECK_ALERT_RULE, rule_id=str(rule_id))

    async def run_turn(self, turn_id: Id) -> None:
        await self._kick(RUN_TURN, turn_id=str(turn_id))

    async def judge_widget(self, widget_id: Id) -> None:
        await self._kick(JUDGE_WIDGET, widget_id=str(widget_id))

    async def _kick(self, name: str, **arguments: object) -> None:
        # Raises when the task could not be queued: the caller asked for work to happen, so
        # silently dropping it would be wrong.
        try:
            await AsyncKicker(name, self.broker, labels={}).kiq(**arguments)
        except SendTaskError as error:
            reason = str(error.__cause__ or error) or type(error).__name__
            raise Unavailable(f"The task queue could not be reached: {reason}") from error
