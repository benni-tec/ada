from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ada.composition.providers.infrastructure import InfrastructureProvider


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


async def _count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return (await connection.execute(text("SELECT count(*) FROM projects"))).scalar_one()


async def _request(provider: InfrastructureProvider, engine: AsyncEngine, fail: bool) -> None:
    sessions = provider.session(engine)
    session: AsyncSession = await anext(sessions)
    await session.execute(text("INSERT INTO projects VALUES (gen_random_uuid(), 'p', now(), 1)"))
    # What dishka does when the request ends: send None, or the exception it raised.
    with pytest.raises(StopAsyncIteration):
        await sessions.asend(RuntimeError("request failed") if fail else None)


@pytest.mark.anyio
async def test_a_request_commits_on_success_and_rolls_back_when_it_raises(
    engine: AsyncEngine,
) -> None:
    provider = InfrastructureProvider()
    await _request(provider, engine, fail=True)
    assert await _count(engine) == 0
    await _request(provider, engine, fail=False)
    assert await _count(engine) == 1
