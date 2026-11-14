from pathlib import Path
from uuid import uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider

from ada.adapters.db.workspace_repositories import SqlProjectRepository
from ada.composition import create_container, providers
from ada.composition import unbuilt as unbuilt_module
from ada.composition.unbuilt import Unbuilt
from ada.config import Settings
from ada.core.ports.repositories import ProjectRepository
from ada.core.services.dashboards.service import Dashboards
from ada.core.services.ports.dashboards import DashboardService
from ada.discovery import modules

pytestmark = pytest.mark.anyio


def test_every_provider_module_exposes_a_provider() -> None:
    found = modules(providers)
    assert len(found) >= 2
    assert all(hasattr(module, "provider") for module in found)


async def test_the_container_resolves_bound_ports(unreachable_settings: Settings) -> None:
    container = create_container(unreachable_settings, FastapiProvider())
    try:
        async with container() as request:
            # Resolving opens no connection yet, so this works with the database down.
            assert isinstance(await request.get(ProjectRepository), SqlProjectRepository)
            assert isinstance(await request.get(DashboardService), Dashboards)
    finally:
        await container.close()


def test_no_port_is_bound_to_the_unbuilt_stand_in() -> None:
    # Every port has a real implementation since wave 2. The stand-in stays for ports a
    # later wave adds, so a branch starts before they are built; none may ship on it.
    standing_in = [
        factory.provides.type_hint
        for module in modules(providers)
        for factory in module.provider.factories
        if getattr(factory.source, "__module__", None) == unbuilt_module.__name__
    ]
    assert standing_in == []


def test_the_unbuilt_stand_in_says_what_is_missing() -> None:
    with pytest.raises(NotImplementedError, match="DashboardService"):
        Unbuilt(DashboardService).list(uuid7())


async def test_repositories_store_through_the_request_session_and_commit_with_it(
    migrated_database_url: str, tmp_path: Path
) -> None:
    import factories

    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    container = create_container(settings, FastapiProvider())
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
        async with container() as request:
            assert await (await request.get(ProjectRepository)).list() == [project]
    finally:
        await container.close()
