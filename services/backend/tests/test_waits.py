"""`ada seed-waits` on the wellbeing areas' pages as recorded on 2026-11-14 (Markdown, cut to
the lines the SQL reads): the whole path from scrape to widget rows and the alert, with
only Context.dev's HTTP replaced."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope

from ada.adapters.clock import SystemClock
from ada.adapters.memory.web import MemoryWebBudget
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli import waiting_times as waits
from memory import MemoryBackground

pytestmark = pytest.mark.anyio

PAGES = Path(__file__).parent / "recordings" / "waits"
RECORDED = {
    waits.KAINUU.address: "kainuu.md",
    waits.KAINUU_ARCHIVED.address: "kainuu-2026-04-16.md",
    waits.SATAKUNTA.address: "satakunta.md",
    waits.POHJANMAA.address: "pohjanmaa.md",
    waits.HOITOJONOT.address: "hoitojonot.md",
}


def context_dev(request: httpx.Request) -> httpx.Response:
    assert (request.method, request.url.path) == ("POST", "/v1/web/scrape")
    url = json.loads(request.content)["url"]
    markdown = (PAGES / RECORDED[url]).read_text()
    return httpx.Response(
        200, json={"url": url, "markdown": {"success": True, "data": markdown}, "metadata": {}}
    )


@pytest.fixture
async def container(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[AsyncContainer]:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    readers = HttpSourceReaders(
        create_client(httpx.MockTransport(context_dev)),
        SystemClock(),
        context_dev_key="test-key",
        web_budget=MemoryWebBudget(),
        web_daily_credit_limit=100,
    )
    outside = Provider(scope=Scope.APP)
    outside.provide(lambda: readers, provides=SourceReaders)
    container = create_container(settings, MemoryBackground(), outside)
    try:
        yield container
    finally:
        await container.close()


async def test_the_areas_pages_become_one_table_and_kajaanis_longer_queue_an_alert(
    container: AsyncContainer,
) -> None:
    project_id = await waits.seed_waits(container, refresh=True)

    async with container() as request:
        widgets = await request.get(WidgetService)
        tables = {w.title: w for w in await widgets.list(project_id)}
        callbacks = await widgets.data(tables["Callback time per health station, latest month"].id)
        queue = await widgets.data(
            tables["Kajaani: months in the queue for a non-urgent doctor's visit"].id
        )
        coverage = await widgets.data(tables["What each wellbeing area publishes"].id)
        alerts = await request.get(AlertService)
        firing = await alerts.alerts(project_id, AlertState.FIRING)

    def rows(data, *names):  # noqa: ANN001, ANN202
        index = [c.name for c in data.columns]
        return [tuple(row[index.index(n)] for n in names) for row in data.rows]

    # Eight stations in Kainuu and ten in Satakunta, October 2026, longest callback first.
    by_area = rows(callbacks, "area", "data_month")
    assert (by_area.count(("Kainuu", "10/2026")), by_area.count(("Satakunta", "10/2026"))) == (
        8,
        10,
    )
    assert rows(callbacks, "station", "callback_minutes")[0] == (
        "Kajaani, yleislääketieteen poliklinikka ja Vuolijoen terveysaseman vastaanotto",
        430,
    )
    # The same SQL read both copies of Kainuu's page.
    assert rows(queue, "copy", "queue_months") == [
        ("Archived copy (Wayback Machine)", 3.5),
        ("Live page", 5.0),
    ]
    assert {s.name for s in queue.sources} == {waits.KAINUU.name, waits.KAINUU_ARCHIVED.name}
    # Old and unofficial data says so.
    freshness = dict(rows(coverage, "area", "freshness"))
    assert freshness["Satakunta, elderly services"].startswith("stale")
    assert freshness["hoitojonot.fi"].endswith(", unofficial")
    assert "No table" in dict(rows(coverage, "area", "publishes"))["Pohjanmaa"]

    [alert] = firing
    assert alert.key == {"station": rows(queue, "station")[0][0]}
