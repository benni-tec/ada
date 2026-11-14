from collections.abc import Sequence
from typing import Any, Protocol

from ada.core.models.base import DomainModel, Id
from ada.core.models.web import SearchHit, SearchScope, WebLink

# In every answer of the web tools: what an agent finds there is not data the person sees.
EXPLORATION_NOTE = (
    "For your own exploration only. Do not show or quote this to the person: to present "
    'web data, register its URL as a source (register_source, access_kind "web" or '
    '"document") and build on it, so it can be traced.'
)

MAX_SEARCH_RESULTS = 10
MAX_READ_CHARS = 60_000
MAX_EXTRACT_COLUMNS = 30
MAX_INSTRUCTION_CHARS = 2000
MAX_MAP_LINKS = 500
MAX_FOCUS_CHARS = 2000

# What each web tool reserves of the project's daily web credits. Context.dev's are its
# own prices, and a call is corrected afterwards to what it charged when it says (a
# search, a read, an extraction). An Exa search is counted at this fixed weight: the
# recorded search of five results with highlights cost $0.007, several Context.dev
# scrapes' worth, so it counts as much as an extraction. A Context.dev search costs about
# one credit per two to three results (the recorded web search of three with passages 2,
# the news search of three 1); a read of PDF pages with OCR one per page.
WEB_SEARCH_CREDITS = 5
WEB_READ_CREDITS = 1
WEB_EXTRACT_CREDITS = 5
WEB_MAP_CREDITS = 1


class WebSearchAnswer(DomainModel):
    results: list[SearchHit]
    note: str = EXPLORATION_NOTE


class WebReadAnswer(DomainModel):
    url: str
    title: str | None = None
    markdown: str
    # Whether the Markdown was cut at max_chars.
    truncated: bool
    note: str = EXPLORATION_NOTE


class WebExtractAnswer(DomainModel):
    url: str
    # In the columns asked for; null where the page does not state a value.
    rows: list[dict[str, Any]]
    # Whether the page was longer than the extraction reads.
    truncated: bool
    note: str = EXPLORATION_NOTE


class WebMapAnswer(DomainModel):
    links: list[WebLink]
    note: str = EXPLORATION_NOTE


class WebExplorationService(Protocol):
    """Web search (Exa or Context.dev) and Context.dev's scrape, extraction and map on
    ADA's keys, for an agent working in a session of the project (which the caller has
    checked). Each call counts against the project's daily web budget (Invalid once it is
    used up) and is tagged with the project at Context.dev."""

    async def search(
        self,
        project_id: Id,
        session_id: Id,
        query: str,
        scope: SearchScope = SearchScope.DATA,
        limit: int = 8,
    ) -> WebSearchAnswer: ...

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
        """The page's main content as Markdown, or with `query` only the passages relevant
        to it; `pdf_pages` ("25" or "25-26") reads only those pages of a PDF, `ocr` reads
        them with OCR (for tables that are images)."""
        ...

    async def extract(
        self, project_id: Id, session_id: Id, url: str, instruction: str, columns: Sequence[str]
    ) -> WebExtractAnswer: ...

    async def map(
        self,
        project_id: Id,
        session_id: Id,
        domain: str,
        search: str | None = None,
        max_links: int = 50,
    ) -> WebMapAnswer: ...
