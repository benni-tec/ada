"""Exa web search: POST /search with highlights, POST /contents for page text."""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from ada.adapters.web import send_json
from ada.core.models.web import PageText, SearchHit, SearchScope, search_not_configured
from ada.core.ports.web import WebSearch

BASE_URL = "https://api.exa.ai"
SNIPPET_CHARACTERS = 600
PAGE_CHARACTERS = 3000

# Data portals: THL/Sotkanet, Statistics Finland, the Finnish Cancer Registry, NORDCAN/IARC,
# Eurostat, OECD, WHO, Kela, Duodecim, open data portals and repositories.
DATA_DOMAINS = [
    "sotkanet.fi",
    "thl.fi",
    "stat.fi",
    "pxdata.stat.fi",
    "syoparekisteri.fi",
    "cancerregistry.fi",
    "iarc.who.int",
    "gco.iarc.fr",
    "ec.europa.eu",
    "oecd.org",
    "who.int",
    "kela.fi",
    "duodecim.fi",
    "avoindata.fi",
    "zenodo.org",
    "kaggle.com",
    "figshare.com",
]
NEWS_DOMAINS = [
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "theguardian.com",
    "nytimes.com",
    "ft.com",
    "yle.fi",
    "hs.fi",
]
RESEARCH_DOMAINS = [
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "doi.org",
    "nature.com",
    "science.org",
    "thelancet.com",
    "sciencedirect.com",
    "springer.com",
    "semanticscholar.org",
]
DOMAINS: dict[SearchScope, list[str] | None] = {
    SearchScope.DATA: DATA_DOMAINS,
    SearchScope.NEWS: NEWS_DOMAINS,
    SearchScope.RESEARCH: RESEARCH_DOMAINS,
    SearchScope.ANY: None,
}


class ExaSearch(WebSearch):
    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr | None) -> None:
        self.client = client
        self.api_key = api_key

    async def search(self, query: str, scope: SearchScope, limit: int) -> list[SearchHit]:
        body: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": {"maxCharacters": SNIPPET_CHARACTERS}},
        }
        if (domains := DOMAINS[scope]) is not None:
            body["includeDomains"] = domains
        answer = await self._post("/search", body)
        return [
            SearchHit(
                url=result["url"],
                title=result.get("title") or result["url"],
                published=result.get("publishedDate"),
                snippet=" ".join(result.get("highlights") or []),
            )
            for result in answer.get("results", [])
        ]

    async def contents(self, urls: Sequence[str]) -> list[PageText]:
        body = {"urls": list(urls), "text": {"maxCharacters": PAGE_CHARACTERS}}
        answer = await self._post("/contents", body)
        # A page that failed is reported in "statuses" inside an HTTP 200.
        failed = {s.get("id") for s in answer.get("statuses", []) if s.get("status") != "success"}
        return [
            PageText(url=result["url"], title=result.get("title"), text=result["text"])
            for result in answer.get("results", [])
            if result.get("id", result["url"]) not in failed and result.get("text")
        ]

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.api_key is None:
            raise search_not_configured()
        return await send_json(
            self.client, "POST", BASE_URL + path, self.api_key.get_secret_value(), body
        )
