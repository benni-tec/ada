"""Context.dev's web API on ADA's key: scrape (Markdown, the passages relevant to a
question, or a schema's JSON; a PDF's page range and OCR), map, crawl, answers and page
monitors (ContextDevWeb), and web and news search (ContextDevSearch).

Called over REST (https://api.context.dev/v1, `Authorization: Bearer <key>`). Exactly
the parameters of the WebExplorer and WebSearch ports are sent, and every request that
reads carries the caller's `tags`; nothing else of the API (screenshots, browser actions,
profiles, policies, ZDR) is reachable from here. A read that fails keeps HTTP 200 with
`success: false` in its format; only a malformed request is an HTTP error. Such a failure
quotes only its checked error code: the rest of the answer may carry the page's own text.
"""

import html
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from ada.adapters.web import error_code
from ada.adapters.web.scopes import DOMAINS
from ada.core.models.base import JsonObject
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.web import (
    Answer,
    Crawl,
    Extraction,
    Monitor,
    PdfOptions,
    SearchHit,
    SearchResults,
    SearchScope,
    WebLink,
    WebNotConfigured,
    WebPage,
    reading_not_configured,
    search_not_configured,
)
from ada.core.ports.web import WebExplorer, WebSearch

BASE_URL = "https://api.context.dev/v1"
# A crawl stops itself after about 80 seconds; an answer takes up to a few minutes.
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
# What an extraction costs when Context.dev does not say (the recorded one cost 5).
EXTRACT_CREDITS = 5
# Watched pages are checked once a day.
SCHEDULE = {"type": "interval", "frequency": 1, "unit": "days"}
# The passages a focused read returns at most (Context.dev allows 100 to 20,000).
FOCUS_CHARACTERS = 8000
# A search hit's snippet: its passages relevant to the query, at most this long.
SNIPPET_CHARACTERS = 600


class _ContextDev:
    """ADA's key and the one way a request is sent: tagged, the key never in a message."""

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, base_url: str = BASE_URL):
        self.client = client
        self.api_key = api_key
        self.base_url = base_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _not_configured(self) -> WebNotConfigured:
        return reading_not_configured()

    async def _send(
        self, method: str, path: str, what: str, tags: Sequence[str] | None, **kwargs: Any
    ) -> JsonObject:
        if not self.api_key:
            raise self._not_configured()
        if tags is not None and "json" in kwargs:
            kwargs["json"] = {**kwargs["json"], "tags": list(tags)}
        elif tags is not None:
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
        if answer.status_code in (200, 201):
            try:
                body = answer.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                raise Unavailable(f"Context.dev answered {what} with something other than JSON")
            return body
        # The key never goes into a message: an authentication error may echo it.
        reason = _message(answer).replace(self.api_key, "…")
        match answer.status_code:
            case 401 | 403:
                raise Invalid(f"Context.dev refused the key: {reason}")
            case 402:
                raise Invalid(f"Context.dev has no credits left: {reason}")
            case 404 if method == "DELETE":
                raise _Gone(reason)
            case 408 | 429 | 500 | 503 | 504:
                raise Unavailable(f"Context.dev is busy and could not {what}: {reason}")
            case _:
                raise Invalid(f"Context.dev could not {what}: {reason}")

    def _format(self, answer: JsonObject, name: str, url: str) -> Any:
        """The data of one requested format, or Invalid with Context.dev's error code."""
        part = answer.get(name) or {}
        if part.get("success") and part.get("data") is not None:
            return part["data"]
        assert self.api_key  # it answered, so the key was sent
        code = error_code(part, self.api_key) or error_code(answer, self.api_key)
        raise Invalid(f"Context.dev could not read {url}: {code or f'no {name}'}")


class ContextDevWeb(_ContextDev, WebExplorer):
    async def read(
        self,
        url: str,
        *,
        tags: Sequence[str],
        main_content_only: bool = False,
        focus: str | None = None,
        pdf: PdfOptions | None = None,
    ) -> WebPage:
        body: JsonObject = (
            {
                "url": url,
                "formats": {"highlights": True},
                "highlightsParams": {"query": focus, "maxCharacters": FOCUS_CHARACTERS},
            }
            if focus
            else {"url": url, "formats": {"markdown": True}}
        )
        shared = _pdf_params(pdf)
        if main_content_only:
            shared["mainContentOnly"] = True
            if not focus:
                body["markdownParams"] = {"includeLinks": False}
        if shared:
            body["sharedParams"] = shared
        answer = await self._send("POST", "/web/scrape", f"read {url}", tags, json=body)
        if focus:
            passages = self._format(answer, "highlights", url)
            markdown = "\n\n".join(str(passage) for passage in passages or [])
        else:
            markdown = str(self._format(answer, "markdown", url) or "")
        metadata = answer.get("metadata") or {}
        return WebPage(
            url=str(answer.get("url") or url),
            title=metadata.get("title") or None,
            markdown=markdown,
            credits=_stated_credits(answer),
        )

    async def extract(
        self,
        url: str,
        instruction: str,
        columns: Sequence[str],
        *,
        tags: Sequence[str],
        pdf: PdfOptions | None = None,
    ) -> Extraction:
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
        body: JsonObject = {
            "url": url,
            "formats": {"json": True},
            "jsonParams": {"schema": schema, "instructions": instruction},
        }
        if shared := _pdf_params(pdf):
            body["sharedParams"] = shared
        answer = await self._send("POST", "/web/scrape", f"extract from {url}", tags, json=body)
        data = self._format(answer, "json", url)
        rows = data.get("rows") if isinstance(data, dict) else None
        return Extraction(
            rows=[row for row in rows or [] if isinstance(row, dict)],
            truncated=bool((answer.get("json") or {}).get("isTruncated")),
            credits=_credits(answer, EXTRACT_CREDITS),
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

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        body = {
            "name": f"ada {url}"[:120],
            "target": {"type": "page", "url": url},
            "webhook": {"url": webhook_url, "events": ["change.detected"]},
            "schedule": SCHEDULE,
        }
        answer = await self._send("POST", "/monitors", f"watch {url}", None, json=body)
        webhook = answer.get("webhook") or {}
        if not answer.get("id") or not webhook.get("secret"):
            raise Invalid("Context.dev answered the new monitor without its id or secret")
        return Monitor(id=str(answer["id"]), secret=SecretStr(str(webhook["secret"])))

    async def unwatch(self, monitor_id: str) -> None:
        try:
            await self._send("DELETE", f"/monitors/{monitor_id}", "delete the monitor", None)
        except _Gone:
            # Deleted at Context.dev already: the goal is reached.
            pass


class ContextDevSearch(_ContextDev, WebSearch):
    """Web search (POST /web/search) on the scope's sites, with the passages of each hit
    relevant to the query as its snippet; news (POST /news/search) in Context.dev's news
    index, by a natural-language query."""

    def _not_configured(self) -> WebNotConfigured:
        return search_not_configured()

    async def search(
        self, query: str, scope: SearchScope, limit: int, *, tags: Sequence[str]
    ) -> SearchResults:
        if scope is SearchScope.NEWS:
            return await self._news(query, limit, tags)
        body: JsonObject = {
            "query": query,
            "numResults": limit,
            "highlightsOptions": {"enabled": True, "maxCharacters": SNIPPET_CHARACTERS},
        }
        if (domains := DOMAINS[scope]) is not None:
            body["includeDomains"] = domains
        answer = await self._send("POST", "/web/search", "search the web", tags, json=body)
        hits = []
        for result in answer.get("results") or []:
            if not result.get("url"):
                continue
            passages = (result.get("highlights") or {}).get("highlights") or []
            snippet = " ".join(str(passage) for passage in passages) or str(
                result.get("description") or ""
            )
            hits.append(
                SearchHit(
                    url=str(result["url"]),
                    title=result.get("title") or str(result["url"]),
                    snippet=_snippet(snippet),
                )
            )
        return SearchResults(hits=hits, credits=_stated_credits(answer))

    async def _news(self, query: str, limit: int, tags: Sequence[str]) -> SearchResults:
        body: JsonObject = {
            "searchBy": {"type": "natural_language", "query": query},
            "limit": limit,
        }
        answer = await self._send("POST", "/news/search", "search the news", tags, json=body)
        hits = [
            SearchHit(
                url=str(article["url"]),
                title=article.get("title") or str(article["url"]),
                published=article.get("published_at") or None,
                snippet=_snippet(str(article.get("description") or "")),
            )
            for article in answer.get("data") or []
            if article.get("url")
        ]
        return SearchResults(hits=hits, credits=_stated_credits(answer))


class _Gone(Invalid):
    """What was to be deleted is not there."""


def _credits(answer: JsonObject, default: int) -> int:
    consumed = _stated_credits(answer)
    return default if consumed is None else consumed


def _stated_credits(answer: JsonObject) -> int | None:
    """What Context.dev says it charged, or None when it does not say."""
    metadata = answer.get("key_metadata") or {}
    consumed = metadata.get("credits_consumed")
    return consumed if isinstance(consumed, int) and consumed >= 0 else None


def _pdf_params(pdf: PdfOptions | None) -> JsonObject:
    """`sharedParams` reading a PDF's page range, with OCR when asked, each page starting
    with its `<!-- page N -->` line; nothing without PDF options."""
    if pdf is None:
        return {}
    options: JsonObject = {"ocr": "auto" if pdf.ocr else "off", "includeNumberedPages": True}
    if pdf.start is not None:
        options["startPage"] = pdf.start
    if pdf.end is not None:
        options["endPage"] = pdf.end
    return {"parsers": {"pdf": options}}


def _snippet(text: str) -> str:
    """Passages as one line of plain text (Context.dev escapes some spaces as entities),
    at most SNIPPET_CHARACTERS long."""
    text = " ".join(html.unescape(text).split())
    return text if len(text) <= SNIPPET_CHARACTERS else text[: SNIPPET_CHARACTERS - 1] + "…"


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
