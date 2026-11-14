import logging
from uuid import UUID

from dishka.integrations.taskiq import FromDishka

from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.worker.registry import task

logger = logging.getLogger(__name__)


@task()
async def refresh_source(
    data_source_id: str, force: bool = False, *, service: FromDishka[SourceService]
) -> None:
    """Queued when someone asks for a refresh, and for each source that is due."""
    try:
        await service.refresh(UUID(data_source_id), force=force)
    except Exception:
        # The service has recorded the failure and published source.refresh_failed, and the
        # old snapshots stay current; nobody is waiting for the error. Ending normally keeps
        # the worker's log to one entry and lets the task's scope commit what was recorded.
        logger.exception("Refreshing source %s failed", data_source_id)


@task(schedule=[{"cron": "* * * * *"}])
async def refresh_due_sources(
    service: FromDishka[SourceService], dispatcher: FromDishka[TaskDispatcher]
) -> None:
    """Runs every minute and queues a refresh for each source whose freshness policy says
    it is due. Queued rather than run here, so one slow source holds up neither the others
    nor the next tick."""
    for source in await service.due():
        try:
            await dispatcher.refresh_source(source.id)
        except Exception:
            # The source is still due on the next tick, which queues it again.
            logger.exception("Queueing a refresh of source %s failed", source.id)
