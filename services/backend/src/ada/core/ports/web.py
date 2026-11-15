"""The web on ADA's own accounts: Exa or Context.dev searches it, Context.dev reads,
extracts, maps, crawls and watches it, for agents (the web tools) and for web sources."""

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from ada.core.models.base import Id
from ada.core.models.web import (
    Answer,
    Crawl,
    Extraction,
    Monitor,
    PdfOptions,
    SearchResults,
    SearchScope,
    WebLink,
    WebPage,
)


class WebSearch(Protocol):
    """A web search engine: Exa or Context.dev, whichever has a key (Exa first). Raises
    Invalid (search_not_configured) without a key, Invalid or Unavailable when the call
    fails, as the engine's refusal reads."""

    @property
    def configured(self) -> bool:
        """Whether a key is set; without one every call raises Invalid."""
        ...

    async def search(
        self, query: str, scope: SearchScope, limit: int, *, tags: Sequence[str]
    ) -> SearchResults:
        """At most `limit` hits on the scope's sites, each with a snippet of the passages
        that match the query, and what the search cost when the engine says (Context.dev's
        credits). `tags` say on whose behalf it was made, where the engine takes them."""
        ...


class WebExplorer(Protocol):
    """Context.dev: read, extract, map and crawl the web, research answers, and watch
    pages. Every call that reads carries `tags`, which say on whose behalf it was made
    (Context.dev's usage labels). Raises Invalid with a readable reason when the service
    refuses (no key, no credits, a page it cannot read), Unavailable when it is busy or
    unreachable."""

    @property
    def configured(self) -> bool:
        """Whether a key is set; without one every call raises Invalid."""
        ...

    async def read(
        self,
        url: str,
        *,
        tags: Sequence[str],
        main_content_only: bool = False,
        focus: str | None = None,
        pdf: PdfOptions | None = None,
        wait_for: int | str | None = None,
        raw_html: bool = False,
        original_html: bool = False,
    ) -> WebPage:
        """The page as Markdown; with `main_content_only` without navigation and footers.
        With `focus`, only the passages relevant to it (Markdown excerpts in page order,
        separated by blank lines) instead of the whole page. `pdf` reads only some pages of
        a PDF, or with OCR."""
        ...

    async def extract(
        self,
        url: str,
        instruction: str,
        columns: Sequence[str],
        *,
        tags: Sequence[str],
        pdf: PdfOptions | None = None,
        wait_for: int | str | None = None,
    ) -> Extraction:
        """Rows with the given columns, as a model reads them off the page following
        `instruction` (null where the page does not state a value); `pdf` as for read."""
        ...

    async def map(
        self, domain: str, *, search: str | None, max_links: int, tags: Sequence[str]
    ) -> list[WebLink]:
        """The addresses found on a domain (sitemaps and links), most relevant to `search`
        first when given."""
        ...

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
        """The pages of a site from `url` on, as Markdown, in the order crawled."""
        ...

    async def answer(
        self, task: str, json_format: dict[str, Any], *, tags: Sequence[str]
    ) -> Answer:
        """A researched answer to `task` in the shape of the example `json_format`."""
        ...

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        """Watch the page: Context.dev checks it daily and calls the webhook, signed with
        the monitor's secret, when it changed."""
        ...

    async def unwatch(self, monitor_id: str) -> None:
        """Delete the monitor; one that is gone already is no error."""
        ...


class WebBudget(Protocol):
    """The web credits each project spent per day."""

    async def spend(self, project_id: Id, day: date, credits: int, limit: int) -> bool:
        """Count `credits` for the project on `day` unless that would exceed `limit`; then
        count nothing and return False. In a short transaction of its own that has
        committed when this returns, so the credits stay counted when the caller's unit of
        work rolls back."""
        ...

    async def adjust(self, project_id: Id, day: date, credits: int) -> None:
        """Correct the count by `credits` (negative to give back what was reserved but not
        charged), never below zero; likewise in a transaction of its own."""
        ...
