from dishka.integrations.taskiq import FromDishka

from ada.core.services.ports.system import SystemStatusService
from ada.entrypoints.worker.registry import task


@task(schedule=[{"cron": "* * * * *"}])
async def record_heartbeat(service: FromDishka[SystemStatusService]) -> None:
    """Runs every minute, so a fresh heartbeat proves scheduler, queue and worker all work."""
    await service.record_heartbeat()
