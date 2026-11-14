"""Exa web search: POST /search with highlights as snippets, on the scopes' sites
(scopes.py)."""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from ada.adapters.web import send_json
from ada.adapters.web.scopes import DOMAINS
from ada.core.models.web import SearchHit, SearchResults, SearchScope, search_not_configured
from ada.core.ports.web import WebSearch

BASE_URL = "https://api.exa.ai"
SNIPPET_CHARACTERS = 600


class ExaSearch(WebSearch):
    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr | None) -> None:
        self.client = client
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    async def search(
        self, query: str, scope: SearchScope, limit: int, *, tags: Sequence[str]
    ) -> SearchResults:
        # Exa takes no tags; its searches are counted at a fixed weight (credits None).
        body: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": {"maxCharacters": SNIPPET_CHARACTERS}},
        }
        if (domains := DOMAINS[scope]) is not None:
            body["includeDomains"] = domains
        answer = await self._post("/search", body)
        hits = [
            SearchHit(
                url=result["url"],
                title=result.get("title") or result["url"],
                published=result.get("publishedDate"),
                snippet=" ".join(result.get("highlights") or []),
            )
            for result in answer.get("results", [])
        ]
        return SearchResults(hits=hits)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.api_key is None:
            raise search_not_configured()
        return await send_json(
            self.client, "POST", BASE_URL + path, self.api_key.get_secret_value(), body
        )
