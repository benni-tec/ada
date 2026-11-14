from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.base import Id
from ada.core.models.web import SearchScope
from ada.core.services.ports.agents import ResearchService
from ada.core.services.ports.web import (
    MAX_EXTRACT_COLUMNS,
    MAX_MAP_LINKS,
    MAX_READ_CHARS,
    MAX_SEARCH_RESULTS,
    WebExplorationService,
    WebExtractAnswer,
    WebMapAnswer,
    WebReadAnswer,
    WebSearchAnswer,
)
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId

EXPLORATION_ONLY = """

What it returns is for your own exploration only: never show or quote it to the person.
To present web data, register its URL as a source (register_source, access_kind "web" or
"document") and build on it, so it can be traced. Each call spends the project's daily web
credits; in a research session it also counts against the session's web calls."""


def register(mcp: FastMCP, inject: Inject) -> None:
    # A research session's calls count against its cap first, committed at once, so a call
    # that then fails or times out counts too (ResearchService.use_web_call). Other
    # sessions are not capped.

    @mcp.tool(
        description=_described(
            """Search the web (Exa) for data sources, news or research. `scope` "data" (the
        default) limits the search to statistics offices, registries and open-data
        portals, "news" to news, "research" to papers, "any" searches everything. Returns
        each hit's url, title, publication date and a snippet; use read_page to read one.
        Five credits a search."""
        )
    )
    @inject
    async def search_web(
        project_id: Id,
        session_id: SessionId,
        query: str,
        web: FromDishka[WebExplorationService],
        research: FromDishka[ResearchService],
        scope: SearchScope = SearchScope.DATA,
        limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 8,
    ) -> WebSearchAnswer:
        await research.use_web_call(session_id)
        return await web.search(project_id, session_id, query, scope=scope, limit=limit)

    @mcp.tool(
        description=_described(
            """Read one web page as Markdown (Context.dev), its main content without navigation,
        cut at `max_chars` (`truncated` says whether it was): to check what a page holds
        before registering it, or to find the download links of a dataset. One credit."""
        )
    )
    @inject
    async def read_page(
        project_id: Id,
        session_id: SessionId,
        url: str,
        web: FromDishka[WebExplorationService],
        research: FromDishka[ResearchService],
        max_chars: Annotated[int, Field(ge=1, le=MAX_READ_CHARS)] = 20_000,
    ) -> WebReadAnswer:
        await research.use_web_call(session_id)
        return await web.read(project_id, session_id, url, max_chars=max_chars)

    @mcp.tool(
        description=_described(
            """Extract rows with the given `columns` from a web page, following `instruction`
        (Context.dev): to see whether a page holds a table worth registering. The rows are
        model-extracted, not parsed: a value the page does not state comes back null, and
        every figure needs checking against the page. To keep such rows, register the page
        as a web source with operation "extract". About five credits."""
        )
    )
    @inject
    async def extract_table(
        project_id: Id,
        session_id: SessionId,
        url: str,
        instruction: str,
        columns: Annotated[list[str], Field(min_length=1, max_length=MAX_EXTRACT_COLUMNS)],
        web: FromDishka[WebExplorationService],
        research: FromDishka[ResearchService],
    ) -> WebExtractAnswer:
        await research.use_web_call(session_id)
        return await web.extract(project_id, session_id, url, instruction, columns)

    @mcp.tool(
        description=_described(
            """List the pages of a site (from its sitemaps and links), e.g. "thl.fi", most
        relevant to `search` first when given: to find a site's statistics or data pages.
        Returns their URLs and titles. One credit."""
        )
    )
    @inject
    async def map_site(
        project_id: Id,
        session_id: SessionId,
        domain: str,
        web: FromDishka[WebExplorationService],
        research: FromDishka[ResearchService],
        search: str | None = None,
        max_links: Annotated[int, Field(ge=1, le=MAX_MAP_LINKS)] = 50,
    ) -> WebMapAnswer:
        await research.use_web_call(session_id)
        return await web.map(project_id, session_id, domain, search=search, max_links=max_links)


def _described(text: str) -> str:
    return " ".join(text.split()) + EXPLORATION_ONLY
