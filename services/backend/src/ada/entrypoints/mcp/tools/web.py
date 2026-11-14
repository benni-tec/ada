from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.base import Id, JsonObject
from ada.core.models.web import PageText, SearchHit, SearchScope
from ada.core.ports.web import PageReader, WebSearch
from ada.core.services.ports.agents import ResearchService
from ada.entrypoints.mcp.injection import Inject

PAGE_CHARACTERS = 20_000
# Bounds of a call, checked before it is counted or sent: one counted call does not ask
# for much more than the defaults.
MAX_HITS = 20
MAX_INSTRUCTION = 2_000
MAX_COLUMNS = 30
MAX_COLUMN_NAME = 100

Column = Annotated[str, Field(min_length=1, max_length=MAX_COLUMN_NAME)]


def register(mcp: FastMCP, inject: Inject) -> None:
    # A research turn's calls count against its session's cap, and so does an external
    # agent's call naming a research session: before the provider is called, and
    # committed at once, so a call that fails or times out counts too.
    @mcp.tool
    @inject
    async def search_web(
        query: str,
        search: FromDishka[WebSearch],
        research: FromDishka[ResearchService],
        scope: SearchScope = SearchScope.DATA,
        limit: Annotated[int, Field(ge=1, le=MAX_HITS)] = 8,
        session_id: Id | None = None,
    ) -> Sequence[SearchHit]:
        """Search the web (Exa) for data sources, news or research. One paid call. `scope`
        "data" limits the search to statistics and open-data portals, "news" to news,
        "research" to papers, "any" searches everything. Returns hits with url, title,
        publication date and a snippet; use read_page to read one. At most 20 hits."""
        await research.use_web_call(session_id)
        return await search.search(query, scope, limit)

    @mcp.tool
    @inject
    async def read_page(
        url: str,
        pages: FromDishka[PageReader],
        research: FromDishka[ResearchService],
        session_id: Id | None = None,
    ) -> PageText:
        """Read a web page as text (Context.dev). One paid call. The text is cut off at
        20,000 characters, with a note when it was."""
        await research.use_web_call(session_id)
        page = await pages.read(url)
        if len(page.text) > PAGE_CHARACTERS:
            note = f"\n\n[truncated: the page has {len(page.text)} characters]"
            page = page.model_copy(update={"text": page.text[:PAGE_CHARACTERS] + note})
        return page

    @mcp.tool
    @inject
    async def extract_table(
        url: str,
        instruction: Annotated[str, Field(min_length=1, max_length=MAX_INSTRUCTION)],
        columns: Annotated[list[Column], Field(min_length=1, max_length=MAX_COLUMNS)],
        pages: FromDishka[PageReader],
        research: FromDishka[ResearchService],
        session_id: Id | None = None,
    ) -> list[JsonObject]:
        """Extract rows with the given `columns` from a web page, following `instruction`
        (Context.dev). One paid call. The rows are model-extracted, not parsed: a value
        the page does not state comes back null, and every figure needs checking against
        the page before it is relied on. At most 30 columns, named in at most 100
        characters each; the instruction in at most 2,000."""
        await research.use_web_call(session_id)
        return await pages.extract(url, instruction, columns)
