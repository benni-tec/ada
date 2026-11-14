import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from dishka import Provider, Scope

from ada.adapters.notify.http import HttpAlertNotifier
from ada.composition import create_container
from ada.core.ports.notify import AlertNotifier
from alerts_support import AlertOverrides, World, csv
from conftest import settings_in
from memory import memory_adapters

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("failure", [None, "status", "connection"])
async def test_notify_only_after_commit_and_once_when_firing(
    tmp_path: Path, failure: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    received: list[httpx.Request] = []
    ready = asyncio.Event()
    release = asyncio.Event()

    async def send(request: httpx.Request) -> httpx.Response:
        received.append(request)
        if len(received) == 2:
            ready.set()
        await release.wait()
        if failure == "connection":
            raise httpx.ConnectError("secret-topic", request=request)
        return httpx.Response(503 if failure == "status" else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
        notifier = HttpAlertNotifier(
            client,
            "http://127.0.0.1/secret-topic",
            "https://hooks.test/secret",
            "https://ada.test/",
        )
        overrides = AlertOverrides()
        provider = Provider(scope=Scope.APP)
        provider.provide(lambda: notifier, provides=AlertNotifier)
        container = create_container(settings_in(tmp_path), *memory_adapters(), overrides, provider)
        world = World(container, overrides)
        try:
            setup = await world.setup(csv(("north", 2024, 70), ("south", 2024, 90)))
            rule = await world.rule(setup)
            with pytest.raises(RuntimeError):
                async with world.alerts() as service:
                    await service.check(rule.id)
                    assert received == []
                    raise RuntimeError("roll back")
            assert received == []
            # Memory repositories retain writes after errors; use a separate rule for the commit.
            rule = await world.rule(setup, name="Committed alert")
            async with world.alerts() as service:
                (alert,) = await service.check(rule.id)
                assert received == []
            # The commit returned while both destinations are blocked in transport.
            await asyncio.wait_for(ready.wait(), timeout=1)
            release.set()
            await asyncio.gather(*notifier._tasks)
            async with world.alerts() as service:
                assert await service.check(rule.id) == []
            await asyncio.sleep(0)
            assert len(received) == 2
            push, webhook = received
            assert push.headers["Title"] == rule.name
            assert push.headers["Priority"] == "high"
            assert push.headers["Click"] == f"https://ada.test/projects/{setup.project_id}/alerts"
            assert "region: north" in push.content.decode()
            assert alert.started_at.isoformat() in push.content.decode()
            payload = json.loads(webhook.content)
            assert payload["event"] == "alert.firing"
            assert payload["key"] == {"region": "north"}
            assert [row["region"] for row in payload["rows"]] == ["north"]
            assert "secret-topic" not in caplog.text
            assert "/secret" not in caplog.text
        finally:
            await container.close()
