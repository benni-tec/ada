"""Composition root: binds every port to its implementation. Entrypoints get services from
the container built here and never import services or adapters themselves."""

from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, from_context, make_async_container, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ada.adapters.db.database import EngineDatabase
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.valkey.task_queue import ValkeyTaskQueue
from ada.config import Settings
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.system import Database, TaskQueue
from ada.core.services.ports.system import SystemStatusService
from ada.core.services.system import SystemStatus


class InfrastructureProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(
            settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
        )
        yield engine
        await engine.dispose()

    @provide(scope=Scope.REQUEST)
    async def session(self, engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
        # One session per request, shared by its repositories. Commits when the request
        # succeeds, rolls back when it raises.
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            yield session

    @provide(scope=Scope.APP)
    async def valkey(self, settings: Settings) -> AsyncIterator[Redis]:
        client = Redis.from_url(settings.valkey_url, socket_connect_timeout=2, socket_timeout=2)
        yield client
        await client.aclose()


class AdapterProvider(Provider):
    """Outbound ports. The probes live as long as the process and use no request session,
    since they report whether their dependency can be reached at all."""

    scope = Scope.APP

    database = provide(EngineDatabase, provides=Database)
    task_queue = provide(ValkeyTaskQueue, provides=TaskQueue)

    @provide
    def analysis_store(self, settings: Settings) -> AnalysisStore:
        return DuckDbAnalysisStore(settings.data_dir)


class ServiceProvider(Provider):
    """Inbound ports."""

    scope = Scope.REQUEST

    system_status = provide(SystemStatus, provides=SystemStatusService, scope=Scope.APP)


def create_container(settings: Settings, *providers: Provider) -> AsyncContainer:
    """Container shared by every entrypoint; each adds its framework provider. Providers
    passed later override earlier ones, which tests use to swap in fakes."""
    return make_async_container(
        InfrastructureProvider(),
        AdapterProvider(),
        ServiceProvider(),
        *providers,
        context={Settings: settings},
    )
