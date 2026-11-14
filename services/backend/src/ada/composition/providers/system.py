from dishka import Provider, Scope, provide

from ada.adapters.db.database import EngineDatabase
from ada.adapters.valkey.task_queue import ValkeyTaskQueue
from ada.core.ports.system import Database, TaskQueue
from ada.core.services.ports.system import SystemStatusService
from ada.core.services.system import SystemStatus


class SystemProvider(Provider):
    """Health. The probes live as long as the process and use no request session, since
    they report whether their dependency can be reached at all."""

    scope = Scope.APP

    database = provide(EngineDatabase, provides=Database)
    task_queue = provide(ValkeyTaskQueue, provides=TaskQueue)
    system_status = provide(SystemStatus, provides=SystemStatusService)


provider = SystemProvider()
