from dishka import Provider
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import AsyncBroker, InMemoryBroker, TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from ada.composition import create_container
from ada.config import Settings
from ada.core.services.ports.system import SystemStatusService
from ada.discovery import modules
from ada.entrypoints.worker import tasks
from ada.entrypoints.worker.registry import TASKS


def create_broker(settings: Settings, *providers: Provider, in_memory: bool = False) -> AsyncBroker:
    """A broker with every task registered.

    The worker uses Valkey. in_memory runs each task right away in the calling process.
    providers override the composition root's, e.g. fakes in tests.
    """
    container = create_container(settings, TaskiqProvider(), *providers)
    broker = InMemoryBroker() if in_memory else RedisStreamBroker(settings.valkey_url)
    setup_dishka(container, broker)
    # Importing the task modules is what declares their tasks.
    modules(tasks)
    for task in TASKS:
        broker.register_task(task.function, task.name, schedule=task.schedule)

    if not in_memory:

        @broker.on_event(TaskiqEvents.WORKER_STARTUP)
        async def _startup(state: TaskiqState) -> None:
            # Report alive right away instead of waiting for the first scheduled heartbeat.
            await (await container.get(SystemStatusService)).record_heartbeat()

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def _shutdown(state: TaskiqState) -> None:
        await container.close()

    return broker


def create_scheduler(broker: AsyncBroker) -> TaskiqScheduler:
    # Schedules come from the `schedule` label of each task.
    return TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
