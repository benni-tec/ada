from collections.abc import Sequence
from datetime import date

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.web import (
    PdfOptions,
    SearchScope,
    pdf_page_range,
    reading_not_configured,
    search_not_configured,
)
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer, WebSearch
from ada.core.services.ports.web import (
    MAX_EXTRACT_COLUMNS,
    MAX_FOCUS_CHARS,
    MAX_INSTRUCTION_CHARS,
    MAX_MAP_LINKS,
    MAX_READ_CHARS,
    MAX_SEARCH_RESULTS,
    WEB_EXTRACT_CREDITS,
    WEB_MAP_CREDITS,
    WEB_READ_CREDITS,
    WEB_SEARCH_CREDITS,
    WebExplorationService,
    WebExtractAnswer,
    WebMapAnswer,
    WebReadAnswer,
    WebSearchAnswer,
)


class WebExploration(WebExplorationService):
    """Each call checks its arguments and that the service's key is set, then spends the
    project's credits for the day (their own transaction: a call that was sent stays
    counted when it fails), then asks the search engine or Context.dev, tagged with the
    project, and corrects the reservation to what Context.dev says it charged. That the
    session is in the project, the MCP tools' session middleware has
    checked before the call (SessionToolCalls); nothing here reads the database, so no
    connection is held while Exa or Context.dev works."""

    def __init__(
        self,
        search_engine: WebSearch,
        explorer: WebExplorer,
        budget: WebBudget,
        clock: Clock,
        daily_credit_limit: int,
    ) -> None:
        self.search_engine = search_engine
        self.explorer = explorer
        self.budget = budget
        self.clock = clock
        self.limit = daily_credit_limit

    async def search(
        self,
        project_id: Id,
        session_id: Id,
        query: str,
        scope: SearchScope = SearchScope.DATA,
        limit: int = 8,
    ) -> WebSearchAnswer:
        if not query.strip():
            raise Invalid("A web search needs a query")
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise Invalid(f"limit is between 1 and {MAX_SEARCH_RESULTS}")
        if not self.search_engine.configured:
            raise search_not_configured()
        await self._spend(project_id, WEB_SEARCH_CREDITS)
        found = await self.search_engine.search(query.strip(), scope, limit, tags=_tags(project_id))
        await self._correct(project_id, WEB_SEARCH_CREDITS, found.credits)
        return WebSearchAnswer(results=list(found.hits))

    async def read(
        self,
        project_id: Id,
        session_id: Id,
        url: str,
        max_chars: int = 20_000,
        query: str | None = None,
        pdf_pages: str | None = None,
        ocr: bool = False,
    ) -> WebReadAnswer:
        url = _url(url, "read_page")
        if not 1 <= max_chars <= MAX_READ_CHARS:
            raise Invalid(f"max_chars is between 1 and {MAX_READ_CHARS}")
        focus = (query or "").strip() or None
        if focus is not None and len(focus) > MAX_FOCUS_CHARS:
            raise Invalid(f"The query of read_page is at most {MAX_FOCUS_CHARS} characters")
        pdf = None
        if pdf_pages is not None and pdf_pages.strip():
            start, end = pdf_page_range(pdf_pages)
            pdf = PdfOptions(start=start, end=end, ocr=ocr)
        elif ocr:
            pdf = PdfOptions(ocr=True)
        tags = await self._context_dev(project_id, session_id, WEB_READ_CREDITS)
        page = await self.explorer.read(
            url, tags=tags, main_content_only=True, focus=focus, pdf=pdf
        )
        await self._correct(project_id, WEB_READ_CREDITS, page.credits)
        return WebReadAnswer(
            url=page.url,
            title=page.title,
            markdown=page.markdown[:max_chars],
            truncated=len(page.markdown) > max_chars,
        )

    async def extract(
        self, project_id: Id, session_id: Id, url: str, instruction: str, columns: Sequence[str]
    ) -> WebExtractAnswer:
        url = _url(url, "extract_table")
        if not instruction.strip() or len(instruction) > MAX_INSTRUCTION_CHARS:
            raise Invalid(f"The instruction is 1 to {MAX_INSTRUCTION_CHARS} characters")
        names = [column.strip() for column in columns]
        if not names or len(names) > MAX_EXTRACT_COLUMNS or not all(names):
            raise Invalid(f"columns names 1 to {MAX_EXTRACT_COLUMNS} columns")
        if len(set(names)) != len(names):
            raise Invalid("The columns' names are unique")
        tags = await self._context_dev(project_id, session_id, WEB_EXTRACT_CREDITS)
        extraction = await self.explorer.extract(url, instruction.strip(), names, tags=tags)
        await self._correct(project_id, WEB_EXTRACT_CREDITS, extraction.credits)
        return WebExtractAnswer(url=url, rows=extraction.rows, truncated=extraction.truncated)

    async def map(
        self,
        project_id: Id,
        session_id: Id,
        domain: str,
        search: str | None = None,
        max_links: int = 50,
    ) -> WebMapAnswer:
        if not domain.strip():
            raise Invalid("map_site needs a domain, e.g. thl.fi")
        if not 1 <= max_links <= MAX_MAP_LINKS:
            raise Invalid(f"max_links is between 1 and {MAX_MAP_LINKS}")
        tags = await self._context_dev(project_id, session_id, WEB_MAP_CREDITS)
        links = await self.explorer.map(
            domain.strip(), search=search or None, max_links=max_links, tags=tags
        )
        return WebMapAnswer(links=links)

    async def _context_dev(self, project_id: Id, session_id: Id, credits: int) -> tuple[str, ...]:
        if not self.explorer.configured:
            raise reading_not_configured()
        await self._spend(project_id, credits)
        return _tags(project_id)

    async def _correct(self, project_id: Id, reserved: int, charged: int | None) -> None:
        """Count what was charged instead of what was reserved, when the service said."""
        if charged is not None and charged != reserved:
            await self.budget.adjust(project_id, self._day(), charged - reserved)

    async def _spend(self, project_id: Id, credits: int) -> None:
        if not await self.budget.spend(project_id, self._day(), credits, self.limit):
            raise Invalid(
                f"The web budget of this project ({self.limit} credits a day) is used up for today"
            )

    def _day(self) -> date:
        return self.clock.now().date()


def _tags(project_id: Id) -> tuple[str, ...]:
    return ("ada", f"project:{project_id}")


def _url(url: str, tool: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise Invalid(f"{tool} reads an http(s) URL")
    return url
