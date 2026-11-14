from typing import Any

from dishka import Provider
from dishka.integrations.taskiq import CONTAINER_ID, CONTAINER_REGISTRY, TaskiqProvider
from dishka.integrations.taskiq import ContainerMiddleware as DishkaContainerMiddleware
from taskiq import (
    AsyncBroker,
    InMemoryBroker,
    TaskiqEvents,
    TaskiqMessage,
    TaskiqResult,
    TaskiqScheduler,
    TaskiqState,
)
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from ada.composition import create_container
from ada.config import Settings
from ada.core.ports.secrets import SecretBox
from ada.core.services.ports.system import SystemStatusService
from ada.discovery import modules
from ada.entrypoints.worker import tasks
from ada.entrypoints.worker.registry import TASKS


class ContainerMiddleware(DishkaContainerMiddleware):
    """dishka's request scope per task, ended with the task's exception when it raises.

    dishka's own middleware ends a failed task's scope as if it had succeeded, which would
    commit what the task wrote before failing and broadcast its events.
    """

    async def on_error(
        self, message: TaskiqMessage, result: TaskiqResult[Any], exception: BaseException
    ) -> None:
        if CONTAINER_ID not in message.labels:
            return
        registry = self.broker.state[CONTAINER_REGISTRY]
        container = registry.pop(message.labels.pop(CONTAINER_ID), None)
        if container is not None:
            await container.close(exception)


def create_broker(settings: Settings, *providers: Provider, in_memory: bool = False) -> AsyncBroker:
    """A broker with every task registered.

    The worker uses Valkey. in_memory runs each task right away in the calling process.
    providers override the composition root's, e.g. fakes in tests.
    """
    container = create_container(settings, TaskiqProvider(), *providers)
    broker = InMemoryBroker() if in_memory else RedisStreamBroker(settings.valkey_url)
    broker.add_middlewares(ContainerMiddleware(container))
    # Importing the task modules is what declares their tasks.
    modules(tasks)
    for task in TASKS:
        broker.register_task(task.function, task.name, schedule=task.schedule)

    if not in_memory:

        @broker.on_event(TaskiqEvents.WORKER_STARTUP)
        async def _startup(state: TaskiqState) -> None:
            # A master key that is set but malformed stops the worker.
            await container.get(SecretBox)
            # Report alive right away instead of waiting for the first scheduled heartbeat.
            await (await container.get(SystemStatusService)).record_heartbeat()

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def _shutdown(state: TaskiqState) -> None:
        await container.close()

    return broker


def create_scheduler(broker: AsyncBroker) -> TaskiqScheduler:
    # Schedules come from the `schedule` label of each task.
    return TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
