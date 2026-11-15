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


@pytest.mark.parametrize("status", [200, 503])
async def test_delivery_records_and_simulated_email(tmp_path: Path, status: int) -> None:
    from ada.core.models.alerts import AlertDelivery

    recorded: list[AlertDelivery] = []

    async def record(delivery: AlertDelivery) -> None:
        recorded.append(delivery)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        notifier = HttpAlertNotifier(
            client,
            None,
            "https://hooks.test/secret",
            "https://ada.test",
            " pharmacy@hospital.example, nurse@hospital.example ",
            record,
        )
        overrides = AlertOverrides()
        provider = Provider(scope=Scope.APP)
        provider.provide(lambda: notifier, provides=AlertNotifier)
        container = create_container(settings_in(tmp_path), *memory_adapters(), overrides, provider)
        world = World(container, overrides)
        try:
            setup = await world.setup(csv(("north", 2024, 70)))
            rule = await world.rule(setup)
            async with world.alerts() as service:
                await service.test(rule.id)
                assert await service.alerts(setup.project_id) == []
                assert (await service.get_rule(rule.id)).last_checked_at is None
                assert recorded == []
            await notifier.drain()
            assert len(recorded) == 3
            webhook = next(item for item in recorded if item.channel == "webhook")
            assert webhook.status == ("sent" if status == 200 else "failed")
            assert webhook.http_status == status
            assert webhook.target == "hooks.test"
            assert all(item.test and item.alert_id is None for item in recorded)
            emails = [item for item in recorded if item.channel == "email"]
            assert {item.target for item in emails} == {
                "pharmacy@hospital.example",
                "nurse@hospital.example",
            }
            assert all(item.status == "simulated" for item in emails)
            assert all(
                item.detail
                and "Subject: [TEST]" in item.detail
                and "region: north" in item.detail
                and f"/projects/{setup.project_id}/alerts" in item.detail
                for item in emails
            )
            async with world.alerts() as service:
                assert await service.alerts(setup.project_id) == []
        finally:
            await container.close()


async def test_delivery_migration_commit_and_live_event(postgres) -> None:
    import importlib
    import os
    from datetime import UTC, datetime
    from uuid import uuid4

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from psycopg import sql
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from ada.adapters.db.deliveries import SqlDeliveryRepository
    from ada.core.models.alerts import AlertDelivery
    from ada.core.models.events import EventType

    schema = f"delivery_test_{uuid4().hex}"
    postgres.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        connect_args={
            "options": f"-c search_path={schema} -c statement_timeout=3000",
            "connect_timeout": 2,
        },
    )
    project_id, rule_id = uuid4(), uuid4()
    published = []

    class Events:
        async def publish(self, event):
            # A separate session must see it before the event is broadcast.
            assert len(await repository.list(project_id)) == 1
            published.append(event)

    repository = SqlDeliveryRepository(engine, Events())
    migration = importlib.import_module("ada.adapters.db.migrations.versions.0015_alert_deliveries")
    try:
        async with engine.begin() as connection:
            for table in ("projects", "alert_rules", "alerts"):
                await connection.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO projects VALUES (:id)"), {"id": project_id})
            await connection.execute(text("INSERT INTO alert_rules VALUES (:id)"), {"id": rule_id})

            def upgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()

            await connection.run_sync(upgrade)
        delivery = AlertDelivery(
            id=uuid4(),
            project_id=project_id,
            rule_id=rule_id,
            test=True,
            channel="email",
            target="pharmacy@hospital.example",
            status="simulated",
            detail="Subject: Test\n\nSample row",
            created_at=datetime.now(UTC),
        )
        await repository.add(delivery)
        assert await repository.list(project_id) == [delivery]
        assert published[0].type == EventType.ALERT_DELIVERED
        assert await repository.list(uuid4()) == []
        async with engine.begin() as connection:

            def downgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.downgrade()

            await connection.run_sync(downgrade)
    finally:
        await engine.dispose()
        postgres.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
