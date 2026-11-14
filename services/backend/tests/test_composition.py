import pytest
from dishka.integrations.fastapi import FastapiProvider

from ada.composition import create_container, providers
from ada.config import Settings
from ada.core.ports.repositories import ProjectRepository
from ada.core.services.ports.pipelines import PipelineService
from ada.discovery import modules

pytestmark = pytest.mark.anyio


def test_every_provider_module_exposes_a_provider() -> None:
    found = modules(providers)
    assert len(found) >= 2
    assert all(hasattr(module, "provider") for module in found)


async def test_the_container_resolves_bound_and_unbuilt_ports(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, FastapiProvider())
    try:
        async with container() as request:
            # Bound to a real implementation.
            projects = await request.get(ProjectRepository)
            assert await projects.list() == []
            # Not implemented yet: resolving works, using it says what is missing.
            pipelines = await request.get(PipelineService)
            with pytest.raises(NotImplementedError, match="PipelineService"):
                await pipelines.get("op_missing")
    finally:
        await container.close()


async def test_memory_repositories_share_one_store_across_requests(
    unreachable_settings: Settings,
) -> None:
    import factories

    container = create_container(unreachable_settings, FastapiProvider())
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
        async with container() as request:
            assert await (await request.get(ProjectRepository)).list() == [project]
    finally:
        await container.close()
