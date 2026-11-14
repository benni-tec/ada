from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.base import Id
from ada.core.services.ports.web import (
    MAX_MAP_LINKS,
    MAX_READ_CHARS,
    MAX_SEARCH_RESULTS,
    WebExplorationService,
    WebMapAnswer,
    WebReadAnswer,
    WebSearchAnswer,
)
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def web_search(
        project_id: Id,
        session_id: Id,
        query: str,
        web: FromDishka[WebExplorationService],
        num_results: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        country: str | None = None,
        languages: list[str] | None = None,
    ) -> WebSearchAnswer:
        """Search the web to find where data lives: statistics offices, registries, open
        data portals, reports. `country` is a two-letter code that localizes results;
        `languages` are codes such as "en" or "fi"; `include_domains` and
        `exclude_domains` narrow the sites. Returns each result's title, URL and snippet.
        One credit per ten results.

        What it returns is for your own exploration only: never show or quote it to the
        person. To present web data, register its URL as a source (register_source,
        access_kind "web" or "document") and build on it, so it can be traced. Each call
        spends the project's daily web credits."""
        return await web.search(
            project_id,
            session_id,
            query,
            num_results=num_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            country=country,
            languages=languages,
        )

    @mcp.tool
    @inject
    async def web_read(
        project_id: Id,
        session_id: Id,
        url: str,
        web: FromDishka[WebExplorationService],
        max_chars: Annotated[int, Field(ge=1, le=MAX_READ_CHARS)] = 20_000,
    ) -> WebReadAnswer:
        """Read one web page as Markdown, cut at `max_chars` (`truncated` says whether it
        was), e.g. to check what a page holds before registering it, or to find the
        download links of a dataset. One credit.

        What it returns is for your own exploration only: never show or quote it to the
        person. To present web data, register its URL as a source (register_source,
        access_kind "web" or "document") and build on it, so it can be traced. Each call
        spends the project's daily web credits."""
        return await web.read(project_id, session_id, url, max_chars=max_chars)

    @mcp.tool
    @inject
    async def web_map(
        project_id: Id,
        session_id: Id,
        domain: str,
        web: FromDishka[WebExplorationService],
        search: str | None = None,
        max_links: Annotated[int, Field(ge=1, le=MAX_MAP_LINKS)] = 50,
    ) -> WebMapAnswer:
        """List the pages of a site (from its sitemaps and links), e.g. "thl.fi", most
        relevant to `search` first when given: to find a site's statistics or data pages.
        Returns their URLs and titles. One credit.

        What it returns is for your own exploration only: never show or quote it to the
        person. To present web data, register its URL as a source (register_source,
        access_kind "web" or "document") and build on it, so it can be traced. Each call
        spends the project's daily web credits."""
        return await web.map(project_id, session_id, domain, search=search, max_links=max_links)
