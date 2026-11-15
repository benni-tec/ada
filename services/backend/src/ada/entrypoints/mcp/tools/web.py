from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.base import Id
from ada.core.models.web import SearchScope
from ada.core.services.ports.agents import ResearchService
from ada.core.services.ports.web import (
    MAX_COLUMN_CHARS,
    MAX_EXTRACT_COLUMNS,
    MAX_FOCUS_CHARS,
    MAX_INSTRUCTION_CHARS,
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

# Checked by the tool's arguments, before a call is counted against the research cap.
Instruction = Annotated[str, Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)]
Column = Annotated[str, Field(min_length=1, max_length=MAX_COLUMN_CHARS)]

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
            """Search the web (ADA's web search) for data sources, news or research. `scope`
        "data" (the default) limits the search to statistics offices, registries and
        open-data portals (THL, Sotkanet, Statistics Finland, the Cancer Registry, the
        Nordic health data authorities, IARC, Eurostat, OECD, WHO, ...), "research" to
        papers (PubMed, PubMed Central, preprint servers and journals such as Acta
        Oncologica, BMJ, The Lancet), "news" to news articles, "any" searches everything.
        Returns each hit's url, title, publication date when known and a snippet of the
        passages that match; use read_page to read one. About five credits a search."""
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
            """Read one web page or PDF as Markdown (Context.dev), its main content without
        navigation, cut at `max_chars` (`truncated` says whether it was): to check what a
        page holds before registering it, or to find the download links of a dataset. With
        `query` (a question or topic) only the passages relevant to it come back instead
        of the whole page: use it to check a figure on a long page or PDF cheaply. For a
        PDF, `pdf_pages` ("25" or "25-26") reads only those pages, each starting with a
        `<!-- page N -->` line, and `ocr` reads them with OCR, for tables that are images
        (empty or garbled without it). For JS-loaded data, wait_for is a delay in
        milliseconds (0–30000) or a CSS
        selector. With raw_html=true, the markdown field contains rendered HTML, including
        scripts and hidden links, to discover a JS page's public data endpoint. Then query
        is a literal substring to find in that HTML (bounded excerpts across up to six
        occurrences, so repeated library boilerplate does not hide later application code).
        For JavaScript/source-code URLs, use raw_html=true with a literal query: semantic
        highlights are not exact code search. Reading HTML never clicks or submits anything.
        original_html=true reads the original HTTP HTML before JS removes paginated rows
        (same literal-query behavior).
        Reads bypass the upstream cache. One credit, a page of a PDF with OCR
        one each."""
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
        query: Annotated[str | None, Field(max_length=MAX_FOCUS_CHARS)] = None,
        pdf_pages: str | None = None,
        ocr: bool = False,
        wait_for: int | str | None = None,
        raw_html: bool = False,
        original_html: bool = False,
    ) -> WebReadAnswer:
        await research.use_web_call(session_id)
        return await web.read(
            project_id,
            session_id,
            url,
            max_chars=max_chars,
            query=query,
            pdf_pages=pdf_pages,
            ocr=ocr,
            wait_for=wait_for,
            raw_html=raw_html,
            original_html=original_html,
        )

    @mcp.tool(
        description=_described(
            """Extract rows with the given `columns` from a web page, following `instruction`
        (Context.dev): to see whether a page holds a table worth registering. The rows are
        model-extracted, not parsed: a value the page does not state comes back null, and
        every figure needs checking against the page. To keep such rows, register the page
        as a web source with operation "extract". For JS-loaded data, wait_for is
        milliseconds (0–30000) or a CSS selector.
        About five credits."""
        )
    )
    @inject
    async def extract_table(
        project_id: Id,
        session_id: SessionId,
        url: str,
        instruction: Instruction,
        columns: Annotated[list[Column], Field(min_length=1, max_length=MAX_EXTRACT_COLUMNS)],
        web: FromDishka[WebExplorationService],
        research: FromDishka[ResearchService],
        wait_for: int | str | None = None,
    ) -> WebExtractAnswer:
        await research.use_web_call(session_id)
        return await web.extract(
            project_id, session_id, url, instruction, columns, wait_for=wait_for
        )

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
