"""The source ports are bound to their implementations."""

import pytest
from dishka.integrations.fastapi import FastapiProvider

from ada.adapters.sources.http import HttpSourceReaders
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Invalid
from ada.core.models.sources import AccessKind
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources

pytestmark = pytest.mark.anyio


async def test_the_container_provides_the_readers_and_the_service(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, FastapiProvider())
    try:
        readers = await container.get(SourceReaders)
        assert isinstance(readers, HttpSourceReaders)
        with pytest.raises(Invalid):
            readers.for_kind(AccessKind.BROWSER)
        async with container() as request:
            service = await request.get(SourceService)
            assert isinstance(service, DataSources)
            # The readers, and with them the HTTP client, are shared by every request.
            assert service.readers is readers
            assert await service.due() == []
    finally:
        await container.close()
    client = readers.readers[AccessKind.URL].client
    assert client.is_closed
