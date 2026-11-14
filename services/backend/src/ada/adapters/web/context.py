"""Context.dev page reading: POST /web/scrape (Markdown, or a schema's JSON, chosen by
formats) and page monitors."""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from ada.adapters.web import ProviderAnswered, error_code, send_json
from ada.core.models.base import JsonObject
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.web import Monitor, PageText, reading_not_configured
from ada.core.ports.web import PageReader

BASE_URL = "https://api.context.dev/v1"
# Watched pages are checked once a day.
SCHEDULE = {"type": "interval", "frequency": 1, "unit": "days"}


class ContextPages(PageReader):
    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr | None) -> None:
        self.client = client
        self.api_key = api_key

    async def read(self, url: str) -> PageText:
        answer = await self._send(
            "POST",
            "/web/scrape",
            {
                "url": url,
                "formats": {"markdown": True},
                "sharedParams": {"mainContentOnly": True},
                "markdownParams": {"includeLinks": False},
            },
        )
        text = self._result(answer, "markdown", url)
        return PageText(url=url, title=(answer.get("metadata") or {}).get("title"), text=text)

    async def extract(self, url: str, instruction: str, columns: Sequence[str]) -> list[JsonObject]:
        # The schema must be a top-level object, so the rows sit in a property. Nullable
        # columns keep the model from guessing a value the page does not state.
        schema = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {c: {"type": ["string", "null"]} for c in columns},
                        "required": list(columns),
                    },
                }
            },
            "required": ["rows"],
        }
        answer = await self._send(
            "POST",
            "/web/scrape",
            {
                "url": url,
                "formats": {"json": True},
                "jsonParams": {"schema": schema, "instructions": instruction},
            },
        )
        if (answer.get("json") or {}).get("isTruncated"):
            # Rows from the cut-off part would be missing without a trace.
            raise Invalid(
                f"{url} is too long for Context.dev to read whole, so the extracted rows would"
                " be incomplete; extract from a shorter page"
            )
        data = self._result(answer, "json", url)
        rows: list[JsonObject] = data.get("rows", []) if isinstance(data, dict) else []
        return rows

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        answer = await self._send(
            "POST",
            "/monitors",
            {
                "name": f"ada {url}"[:120],
                "target": {"type": "page", "url": url},
                "webhook": {"url": webhook_url, "events": ["change.detected"]},
                "schedule": SCHEDULE,
            },
        )
        return Monitor(id=answer["id"], secret=SecretStr(answer["webhook"]["secret"]))

    async def unwatch(self, monitor_id: str) -> None:
        try:
            await self._send("DELETE", f"/monitors/{monitor_id}", None)
        except ProviderAnswered as error:
            # Already deleted at the provider: the goal is reached.
            if error.status != 404:
                raise

    async def _send(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        if self.api_key is None:
            raise reading_not_configured()
        return await send_json(
            self.client, method, BASE_URL + path, self.api_key.get_secret_value(), body
        )

    def _result(self, answer: dict[str, Any], name: str, url: str) -> Any:
        """The data of one requested format. A page that cannot be read still answers HTTP
        200, with success false and an error code; as for an error status, only the code
        is quoted."""
        part = answer.get(name) or {}
        if part.get("success") and part.get("data") is not None:
            return part["data"]
        assert self.api_key is not None  # it answered, so the key was sent
        key = self.api_key.get_secret_value()
        code = error_code(part, key) or error_code(answer, key) or "no content"
        raise Unavailable(f"Context.dev could not read {url}: {code}")
