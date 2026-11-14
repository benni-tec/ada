from collections.abc import Sequence
from typing import Protocol

from ada.core.models.base import DomainModel, Id
from ada.core.ports.web import SearchResult, WebLink

# In every answer of the web tools: what an agent finds there is not data the person sees.
EXPLORATION_NOTE = (
    "For your own exploration only. Do not show or quote this to the person: to present "
    'web data, register its URL as a source (register_source, access_kind "web" or '
    '"document") and build on it, so it can be traced.'
)

MAX_SEARCH_RESULTS = 20
MAX_READ_CHARS = 60_000
MAX_MAP_LINKS = 500


class WebSearchAnswer(DomainModel):
    results: list[SearchResult]
    note: str = EXPLORATION_NOTE


class WebReadAnswer(DomainModel):
    url: str
    title: str | None = None
    markdown: str
    # Whether the Markdown was cut at max_chars.
    truncated: bool
    note: str = EXPLORATION_NOTE


class WebMapAnswer(DomainModel):
    links: list[WebLink]
    note: str = EXPLORATION_NOTE


class WebExplorationService(Protocol):
    """Context.dev's search, scrape and map on ADA's key, for an agent working in a
    session. Each call counts against the project's daily budget (Invalid once it is used
    up) and is tagged with the project."""

    async def search(
        self,
        project_id: Id,
        session_id: Id,
        query: str,
        num_results: int = 10,
        include_domains: Sequence[str] | None = None,
        exclude_domains: Sequence[str] | None = None,
        country: str | None = None,
        languages: Sequence[str] | None = None,
    ) -> WebSearchAnswer: ...

    async def read(
        self, project_id: Id, session_id: Id, url: str, max_chars: int = 20_000
    ) -> WebReadAnswer: ...

    async def map(
        self,
        project_id: Id,
        session_id: Id,
        domain: str,
        search: str | None = None,
        max_links: int = 50,
    ) -> WebMapAnswer: ...
