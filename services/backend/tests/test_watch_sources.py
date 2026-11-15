"""Batch entry points on real services with memory repositories and a fake provider."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from dishka import Provider, Scope
from fastmcp.exceptions import ToolError
from pydantic import SecretStr

from ada.composition.providers.sources import SourceProvider
from ada.core.models.errors import Unavailable
from ada.core.models.sources import CheckEvery
from ada.core.models.web import Monitor
from ada.core.ports.web import WebExplorer
from api_support import FakeWeb, call, mcp_client, new_project, send, serve
from conftest import settings_in
from fakes import FakeExplorer


class SelectiveExplorer(FakeExplorer):
    async def watch(
        self, url: str, webhook_url: str, check_every: CheckEvery | None = None
    ) -> Monitor:
        if url.endswith("/bad"):
            raise Unavailable("provider failure")
        return await super().watch(url, webhook_url, check_every)


def test_batch_isolates_failure_and_reuses_watched_page(tmp_path: Path) -> None:
    settings = settings_in(tmp_path).model_copy(
        update={
            "ada_public_url": "https://ada.test",
            "secret_key": SecretStr(Fernet.generate_key().decode()),
        }
    )
    explorer = SelectiveExplorer()
    provider = Provider()
    provider.provide(lambda: explorer, provides=WebExplorer, scope=Scope.APP)
    with serve(settings, provider) as client:
        project_id = new_project(client)["id"]
        path = f"/projects/{project_id}/sources/watch"
        pages = [
            dict(url=f"https://example.test/{suffix}", name=suffix, check_every="hourly")
            for suffix in ("first", "bad", "last")
        ]
        results = send(client, "POST", path, pages)
        assert [r["ok"] for r in results] == [True, False, True]
        assert explorer.monitors == 2
        again = send(client, "POST", path, [pages[0]])[0]
        assert again["already_watched"] is True
        assert again["source_id"] == results[0]["source_id"]
        assert explorer.monitors == 2
        sources = send(client, "GET", f"/projects/{project_id}/sources")
        assert next(s for s in sources if s["id"] == again["source_id"])["check_every"] == "hourly"
        assert all(call[0] == "watch" for call in explorer.calls)
        send(client, "POST", path, pages * 17, ok=422)
        assert explorer.monitors == 2


@pytest.mark.anyio
async def test_mcp_batch_schema_and_duplicate_urls(tmp_path: Path) -> None:
    settings = settings_in(tmp_path).model_copy(
        update={
            "ada_public_url": "https://ada.test",
            "secret_key": SecretStr(Fernet.generate_key().decode()),
        }
    )
    explorer = FakeExplorer()
    async with mcp_client(settings, SourceProvider(), FakeWeb(explorer=explorer)) as (client, _):
        project = await call(client, "create_project", name="Pages")
        session = await call(client, "create_session", project_id=project["id"], title="Watch")
        arguments = dict(project_id=project["id"], session_id=session["id"])
        page = dict(url="https://example.test/page", name="Page")
        results = await call(client, "watch_sources", **arguments, pages=[page, page])
        assert all(r["ok"] for r in results)
        assert results[1]["already_watched"] is True
        assert explorer.monitors == 1
        with pytest.raises(ToolError):
            await client.call_tool("watch_sources", {**arguments, "pages": [page] * 51})
        assert explorer.monitors == 1
