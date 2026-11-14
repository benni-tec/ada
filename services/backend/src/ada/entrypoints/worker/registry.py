"""How tasks are declared. A module under ada.entrypoints.worker.tasks decorates its
functions with @task; create_broker imports every such module and registers what they
declared, with their schedules."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from dishka.integrations.taskiq import inject

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
    """Declare a task. Its parameters marked FromDishka are injected per call. Its name is
    `<module>:<function>`, which is what a dispatcher uses to enqueue it."""

    def register(function: F) -> F:
        name = f"{function.__module__}:{function.__name__}"
        TASKS.append(Task(name, inject(function, patch_module=True), schedule or []))
        return function

    return register
