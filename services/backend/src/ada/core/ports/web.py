"""The web on ADA's own account (Context.dev): explored by agents, read by web sources."""

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from ada.core.models.base import DomainModel, Id, JsonObject


class SearchResult(DomainModel):
    title: str
    url: str
    snippet: str


class WebPage(DomainModel):
    # The final address, after redirects.
    url: str
    title: str | None = None
    markdown: str


class WebLink(DomainModel):
    url: str
    title: str | None = None


class Crawl(DomainModel):
    pages: list[WebPage]
    # What Context.dev charged; one per page when it does not say.
    credits: int


class Answer(DomainModel):
    # In the shape of the json_format asked for.
    content: JsonObject
    # The URLs the answer read or cites.
    sources: list[str]
    credits: int


class WebExplorer(Protocol):
    """Search, read, map and crawl the web, and research answers. Every call carries
    `tags`, which say on whose behalf it was made (Context.dev's usage labels). Raises
    Invalid with a readable reason when the service refuses (no key, no credits, a page
    it cannot read), Unavailable when it is busy or unreachable."""

    @property
    def configured(self) -> bool:
        """Whether a key is set; without one every call raises Invalid."""
        ...

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
    ) -> list[SearchResult]: ...

    async def read(self, url: str, *, tags: Sequence[str]) -> WebPage:
        """The page as Markdown."""
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


class WebBudget(Protocol):
    """The Context.dev credits each project spent per day."""

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
