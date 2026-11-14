"""Context.dev's web API on ADA's key: search, scrape, map, crawl and answers.

Called over REST (https://api.context.dev/v1, `Authorization: Bearer <key>`). Exactly
the parameters of the WebExplorer port are sent, with Markdown as the only scrape format,
and every request carries the caller's `tags`; nothing else of the API (screenshots,
browser actions, profiles, policies, ZDR) is reachable from here.
"""

from collections.abc import Sequence
from typing import Any

import httpx

from ada.core.models.base import JsonObject
from ada.core.models.errors import Invalid, Unavailable
from ada.core.ports.web import Answer, Crawl, SearchResult, WebExplorer, WebLink, WebPage

BASE_URL = "https://api.context.dev/v1"
# A crawl stops itself after about 80 seconds; an answer takes up to a few minutes.
TIMEOUT = httpx.Timeout(180.0, connect=10.0)


class ContextDevWeb(WebExplorer):
    def __init__(self, client: httpx.AsyncClient, api_key: str | None, base_url: str = BASE_URL):
        self.client = client
        self.api_key = api_key
        self.base_url = base_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        *,
        num_results: int,
        include_domains: Sequence[str] | None,
        exclude_domains: Sequence[str] | None,
        country: str | None,
        languages: Sequence[str] | None,
        tags: Sequence[str],
    ) -> list[SearchResult]:
        body: JsonObject = {"query": query, "numResults": num_results}
        if include_domains:
            body["includeDomains"] = list(include_domains)
        if exclude_domains:
            body["excludeDomains"] = list(exclude_domains)
        if country:
            body["country"] = country.lower()
        if languages:
            body["languages"] = list(languages)
        answer = await self._send("POST", "/web/search", "search the web", tags, json=body)
        return [
            SearchResult(
                title=str(result.get("title") or ""),
                url=str(result.get("url") or ""),
                snippet=str(result.get("description") or ""),
            )
            for result in answer.get("results") or []
            if result.get("url")
        ]

    async def read(self, url: str, *, tags: Sequence[str]) -> WebPage:
        body = {"url": url, "formats": {"markdown": True}}
        answer = await self._send("POST", "/web/scrape", f"read {url}", tags, json=body)
        markdown = answer.get("markdown") or {}
        if not markdown.get("success"):
            reason = markdown.get("message") or markdown.get("error_code") or "no Markdown"
            raise Invalid(f"Context.dev could not read {url}: {reason}")
        metadata = answer.get("metadata") or {}
        return WebPage(
            url=str(answer.get("url") or url),
            title=metadata.get("title") or None,
            markdown=str(markdown.get("data") or ""),
        )

    async def map(
        self, domain: str, *, search: str | None, max_links: int, tags: Sequence[str]
    ) -> list[WebLink]:
        params: dict[str, Any] = {"domain": domain, "maxLinks": max_links}
        if search:
            params["search"] = search
        answer = await self._send("GET", "/web/urls", f"map {domain}", tags, params=params)
        return [
            WebLink(url=str(link["url"]), title=link.get("title") or None)
            for link in answer.get("urls") or []
            if link.get("url")
        ]

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int,
        max_depth: int | None,
        url_regex: str | None,
        exclude_url_regex: str | None,
        tags: Sequence[str],
    ) -> Crawl:
        body: JsonObject = {"url": url, "maxPages": max_pages}
        if max_depth is not None:
            body["maxDepth"] = max_depth
        if url_regex:
            body["urlRegex"] = url_regex
        if exclude_url_regex:
            body["excludeUrlRegex"] = exclude_url_regex
        answer = await self._send("POST", "/web/crawl", f"crawl {url}", tags, json=body)
        pages = []
        for result in answer.get("results") or []:
            metadata = result.get("metadata") or {}
            pages.append(
                WebPage(
                    url=str(metadata.get("finalUrl") or metadata.get("sourceUrl") or url),
                    title=metadata.get("title") or None,
                    markdown=str(result.get("markdown") or ""),
                )
            )
        return Crawl(pages=pages, credits=_credits(answer, len(pages)))

    async def answer(
        self, task: str, json_format: dict[str, Any], *, tags: Sequence[str]
    ) -> Answer:
        body = {"mode": "fast", "task": task, "json_format": json_format}
        answer = await self._send("POST", "/web/answers", "research the task", tags, json=body)
        content = answer.get("json_content")
        if not isinstance(content, dict):
            raise Invalid("Context.dev answered without an answer object")
        sources = [str(source) for source in answer.get("sources") or []]
        return Answer(content=content, sources=sources, credits=_credits(answer, 10))

    async def _send(
        self, method: str, path: str, what: str, tags: Sequence[str], **kwargs: Any
    ) -> JsonObject:
        if not self.api_key:
            raise Invalid(
                "The web needs a Context.dev key: CONTEXT_DEV_API_KEY in the backend's "
                "environment (.env.local in development)"
            )
        if "json" in kwargs:
            kwargs["json"] = {**kwargs["json"], "tags": list(tags)}
        else:
            # A comma-separated list in the query.
            kwargs["params"] = {**kwargs["params"], "tags": ",".join(tags)}
        try:
            answer = await self.client.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=TIMEOUT,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise Unavailable(f"Context.dev could not be reached: {error}") from error
        if answer.status_code == 200:
            body = answer.json()
            if not isinstance(body, dict):
                raise Invalid(f"Context.dev answered {what} with something unexpected")
            return body
        reason = _message(answer)
        match answer.status_code:
            case 401 | 403:
                raise Invalid(f"Context.dev refused the key: {reason}")
            case 402:
                raise Invalid(f"Context.dev has no credits left: {reason}")
            case 408 | 429 | 500 | 503 | 504:
                raise Unavailable(f"Context.dev is busy and could not {what}: {reason}")
            case _:
                raise Invalid(f"Context.dev could not {what}: {reason}")


def _credits(answer: JsonObject, default: int) -> int:
    metadata = answer.get("key_metadata") or {}
    consumed = metadata.get("credits_consumed")
    return consumed if isinstance(consumed, int) and consumed >= 0 else default


def _message(answer: httpx.Response) -> str:
    try:
        body = answer.json()
    except ValueError:
        return f"HTTP {answer.status_code}"
    if isinstance(body, dict):
        detail = body.get("message") or body.get("error") or body.get("error_code")
        if detail:
            return f"{detail} (HTTP {answer.status_code})"
    return f"HTTP {answer.status_code}"
