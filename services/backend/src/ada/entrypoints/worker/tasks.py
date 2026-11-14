"""The worker's tasks. Each calls one use case and returns its result; create_broker
registers them on a broker, with their schedules."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from dishka.integrations.taskiq import FromDishka, inject

from ada.core.services.ports.system import SystemStatusService

type Schedule = list[dict[str, object]]


@dataclass(frozen=True)
class Task:
    # Fixed here: taskiq renames the function it registers, so deriving the name on every
    # registration would change it from the second broker on.
    name: str
    function: Callable[..., Awaitable[Any]]
    schedule: Schedule = field(default_factory=list)


TASKS: list[Task] = []


def task[F: Callable[..., Awaitable[Any]]](schedule: Schedule | None = None) -> Callable[[F], F]:
    def register(function: F) -> F:
        name = f"{function.__module__}:{function.__name__}"
        TASKS.append(Task(name, inject(function, patch_module=True), schedule or []))
        return function

    return register


@task(schedule=[{"cron": "* * * * *"}])
async def record_heartbeat(service: FromDishka[SystemStatusService]) -> None:
    """Runs every minute, so a fresh heartbeat proves scheduler, queue and worker all work."""
    await service.record_heartbeat()
