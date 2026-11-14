from collections.abc import AsyncGenerator, AsyncIterator

from dishka import Provider, Scope, alias, from_context, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ada.adapters.clock import SystemClock
from ada.adapters.transactions import PendingWork
from ada.config import Settings
from ada.core.ports.system import Clock
from ada.core.ports.transactions import AfterCommit


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
    async def pending_work(self) -> AsyncGenerator[PendingWork, BaseException | None]:
        # What waits for the request's commit. The session below depends on this, so dishka
        # creates this first and closes it last: after the session has committed, or after
        # it has rolled back and discarded everything here.
        work = PendingWork()
        exception = yield work
        if exception is None:
            await work.run()

    after_commit = alias(source=PendingWork, provides=AfterCommit, cache=True)

    @provide(scope=Scope.REQUEST)
    async def session(
        self, engine: AsyncEngine, work: PendingWork
    ) -> AsyncGenerator[AsyncSession, BaseException | None]:
        # One session per request, shared by its repositories. Commits when the request
        # succeeds, rolls back when it raises. dishka does not raise the request's exception
        # at the yield; it sends it in, so the outcome is read from what the yield returns.
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            exception = yield session
            if exception is None:
                try:
                    await session.commit()
                except BaseException:
                    work.discard()
                    raise
            else:
                work.discard()
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
