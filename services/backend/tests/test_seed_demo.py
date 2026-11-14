from pathlib import Path

import pytest

from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.sources.examples import EXAMPLES
from ada.composition import create_container
from ada.config import Settings
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.cli.seed import DEMO_PROJECT, seed_demo
from memory import MemoryBackground

pytestmark = pytest.mark.anyio


async def test_seeding_creates_the_demo_project_once(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    container = create_container(settings, MemoryBackground())
    try:
        project_id = await seed_demo(container)
        assert await seed_demo(container, refresh=True) == project_id

        async with container() as request:
            projects = await (await request.get(ProjectService)).list()
            sources = await (await request.get(SourceService)).list(project_id)
        assert [project.name for project in projects] == [DEMO_PROJECT]
        assert [source.name for source in sources] == [example.name for example in EXAMPLES]

        # Registering fetched nothing; the flag queued every source for the worker.
        dispatcher = await container.get(TaskDispatcher)
        assert isinstance(dispatcher, RecordingTaskDispatcher)
        assert dispatcher.refreshes == [(source.id, True) for source in sources]
    finally:
        await container.close()
