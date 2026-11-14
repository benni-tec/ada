"""A failed refresh stays recorded on its source even when the caller's transaction rolls
back, against PostgreSQL and through the container, as the API and the worker use it."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dishka import AsyncContainer, Provider, Scope

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Unavailable
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService
from fakes import FakeSourceReader, FakeSourceReaders
from memory import MemoryBackground

pytestmark = pytest.mark.anyio


@pytest.fixture
def reader() -> FakeSourceReader:
    reader = FakeSourceReader(b"region,value\nHelsinki,74.3\n")
    reader.content = Unavailable("GET https://example.test/data.csv answered 503")
    return reader


@pytest.fixture
async def container(
    migrated_database_url: str, tmp_path: Path, reader: FakeSourceReader
) -> AsyncIterator[AsyncContainer]:
    readers = Provider(scope=Scope.APP)
    readers.provide(lambda: FakeSourceReaders({AccessKind.URL: reader}), provides=SourceReaders)
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    container = create_container(settings, MemoryBackground(), readers)
    yield container
    await container.close()


async def registered(container: AsyncContainer) -> DataSource:
    async with container() as request:
        project = await (await request.get(ProjectService)).create("P")
        return await (await request.get(SourceService)).register(
            project.id, "S", AccessKind.URL, "https://example.test/data.csv", DataFormat.CSV
        )


async def stored(container: AsyncContainer, source: DataSource) -> DataSource:
    async with container() as request:
        return await (await request.get(SourceService)).get(source.id)


async def test_a_failed_refresh_stays_recorded_when_the_caller_rolls_back(
    container: AsyncContainer, reader: FakeSourceReader
) -> None:
    source = await registered(container)
    with pytest.raises(Unavailable):
        async with container() as request:
            await (await request.get(SourceService)).refresh(source.id, force=True)
    after = await stored(container, source)
    assert after.last_error == "GET https://example.test/data.csv answered 503"
    assert after.last_checked_at is not None
    # The record does not count as an edit.
    assert after.revision == source.revision


async def test_a_later_success_clears_the_error(
    container: AsyncContainer, reader: FakeSourceReader
) -> None:
    source = await registered(container)
    with pytest.raises(Unavailable):
        async with container() as request:
            await (await request.get(SourceService)).refresh(source.id, force=True)
    reader.content = b"region,value\nHelsinki,74.3\n"
    async with container() as request:
        result = await (await request.get(SourceService)).refresh(source.id, force=True)
    assert result.changed
    assert (await stored(container, source)).last_error is None
