"""Task worker and scheduler.

    taskiq worker ada.entrypoints.worker:broker
    taskiq scheduler ada.entrypoints.worker:scheduler

Both are created on first access, from the environment's settings, so importing this
package (e.g. for create_broker) does not need a configured environment.
"""

from functools import cache
from typing import Any

from taskiq import AsyncBroker, TaskiqScheduler

from ada.config import Settings
from ada.entrypoints.worker.factory import create_broker, create_scheduler

__all__ = ["broker", "create_broker", "scheduler"]


@cache
def _broker() -> AsyncBroker:
    return create_broker(Settings())


@cache
def _scheduler() -> TaskiqScheduler:
    return create_scheduler(_broker())


def __getattr__(name: str) -> Any:
    if name == "broker":
        return _broker()
    if name == "scheduler":
        return _scheduler()
    raise AttributeError(name)
