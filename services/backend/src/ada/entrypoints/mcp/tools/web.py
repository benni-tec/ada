from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id, JsonObject
from ada.core.models.web import PageText, SearchHit, SearchScope
from ada.core.ports.web import PageReader, WebSearch
from ada.entrypoints.mcp.injection import Inject

PAGE_CHARACTERS = 20_000


def register(mcp: FastMCP, inject: Inject) -> None:
    # `session_id` is unused here; the in-platform toolbox fills it so calls can be counted
    # per session.
    @mcp.tool
    @inject
    async def search_web(
        query: str,
        search: FromDishka[WebSearch],
        scope: SearchScope = SearchScope.DATA,
        limit: int = 8,
        session_id: Id | None = None,
    ) -> Sequence[SearchHit]:
        """Search the web (Exa) for data sources, news or research. One paid call. `scope`
        "data" limits the search to statistics and open-data portals, "news" to news,
        "research" to papers, "any" searches everything. Returns hits with url, title,
        publication date and a snippet; use read_page to read one."""
        return await search.search(query, scope, limit)

    @mcp.tool
    @inject
    async def read_page(
        url: str, pages: FromDishka[PageReader], session_id: Id | None = None
    ) -> PageText:
        """Read a web page as text (Context.dev). One paid call. The text is cut off at
        20,000 characters, with a note when it was."""
        page = await pages.read(url)
        if len(page.text) > PAGE_CHARACTERS:
            note = f"\n\n[truncated: the page has {len(page.text)} characters]"
            page = page.model_copy(update={"text": page.text[:PAGE_CHARACTERS] + note})
        return page

    @mcp.tool
    @inject
    async def extract_table(
        url: str,
        instruction: str,
        columns: list[str],
        pages: FromDishka[PageReader],
        session_id: Id | None = None,
    ) -> list[JsonObject]:
        """Extract rows with the given `columns` from a web page, following `instruction`
        (Context.dev). One paid call. The rows are model-extracted, not parsed: a value
        the page does not state comes back null, and every figure needs checking against
        the page before it is relied on."""
        return await pages.extract(url, instruction, columns)
