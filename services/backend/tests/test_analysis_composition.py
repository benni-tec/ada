import pytest
from dishka.integrations.fastapi import FastapiProvider

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import NotFound
from ada.core.ports.analysis import AnalysisStore
from ada.core.services.pipelines.runs import Runs
from ada.core.services.pipelines.service import Pipelines
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from memory import MemoryRepositories

pytestmark = pytest.mark.anyio


async def test_the_analysis_ports_are_bound_to_the_real_implementations(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, FastapiProvider(), MemoryRepositories())
    try:
        assert isinstance(await container.get(AnalysisStore), DuckDbAnalysisStore)
        async with container() as request:
            pipelines = await request.get(PipelineService)
            runs = await request.get(RunService)
            assert isinstance(pipelines, Pipelines)
            assert isinstance(runs, Runs)
            with pytest.raises(NotFound):
                await pipelines.get("op_missing")
    finally:
        await container.close()
