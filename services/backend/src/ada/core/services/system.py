from ada.core.models.health import Health, Part
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.system import Database, TaskQueue
from ada.core.services.ports.system import SystemStatusService


class SystemStatus(SystemStatusService):
    def __init__(
        self, database: Database, task_queue: TaskQueue, analysis_store: AnalysisStore
    ) -> None:
        self.database = database
        self.task_queue = task_queue
        self.analysis_store = analysis_store

    async def health(self) -> Health:
        database: Part = "ok" if await self.database.is_reachable() else "unavailable"
        queue: Part = "unavailable"
        worker: Part = "unavailable"
        if await self.task_queue.is_reachable():
            queue = "ok"
            worker = "ok" if await self.task_queue.worker_is_alive() else "unavailable"
        analysis_store: Part = "ok" if await self.analysis_store.is_usable() else "unavailable"
        parts = (database, queue, worker, analysis_store)
        return Health(
            status="ok" if all(part == "ok" for part in parts) else "degraded",
            api="ok",
            database=database,
            queue=queue,
            worker=worker,
            analysis_store=analysis_store,
        )

    async def record_heartbeat(self) -> None:
        await self.task_queue.record_heartbeat()
