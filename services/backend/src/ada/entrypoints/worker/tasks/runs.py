import logging
from uuid import UUID

from dishka.integrations.taskiq import FromDishka

from ada.core.services.ports.runs import RunService
from ada.entrypoints.worker.registry import task

logger = logging.getLogger(__name__)


@task()
async def execute(run_id: str, operator_id: str, *, service: FromDishka[RunService]) -> None:
    """Make an operator's output available in a run, materializing what is missing."""
    try:
        await service.execute(UUID(run_id), operator_id)
    except Exception:
        # The service has marked the run failed and published run.failed; nobody is waiting
        # for the error. Ending normally keeps the worker's log to one entry and lets the
        # task's scope commit what was recorded.
        logger.exception("Executing operator %s in run %s failed", operator_id, run_id)
