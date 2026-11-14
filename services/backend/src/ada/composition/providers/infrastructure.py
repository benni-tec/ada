from collections.abc import AsyncGenerator, AsyncIterator

from dishka import Provider, Scope, from_context, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ada.adapters.clock import SystemClock
from ada.config import Settings
from ada.core.ports.system import Clock


class InfrastructureProvider(Provider):
    """Connections and the clock: what adapters are built from."""

    settings = from_context(provides=Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(
            settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
        )
        yield engine
        await engine.dispose()

    @provide(scope=Scope.REQUEST)
    async def session(
        self, engine: AsyncEngine
    ) -> AsyncGenerator[AsyncSession, BaseException | None]:
        # One session per request, shared by its repositories. Commits when the request
        # succeeds, rolls back when it raises. dishka does not raise the request's exception
        # at the yield; it sends it in, so the outcome is read from what the yield returns.
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            exception = yield session
            if exception is None:
                await session.commit()
            else:
                await session.rollback()
        finally:
            await session.close()

    @provide(scope=Scope.APP)
    async def valkey(self, settings: Settings) -> AsyncIterator[Redis]:
        client = Redis.from_url(settings.valkey_url, socket_connect_timeout=2, socket_timeout=2)
        yield client
        await client.aclose()

    clock = provide(SystemClock, provides=Clock, scope=Scope.APP)


provider = InfrastructureProvider()
