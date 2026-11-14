from collections.abc import Sequence
from math import ceil

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.ports.repositories import SessionRepository
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer
from ada.core.services.ports.web import (
    MAX_MAP_LINKS,
    MAX_READ_CHARS,
    MAX_SEARCH_RESULTS,
    WebExplorationService,
    WebMapAnswer,
    WebReadAnswer,
    WebSearchAnswer,
)


class WebExploration(WebExplorationService):
    """Each call checks that the session is in the project and that a key is set, then
    spends the project's credits for the day (their own transaction: a call that was sent
    stays counted when it fails), then asks Context.dev, tagged with the project."""

    def __init__(
        self,
        sessions: SessionRepository,
        explorer: WebExplorer,
        budget: WebBudget,
        clock: Clock,
        daily_credit_limit: int,
    ) -> None:
        self.sessions = sessions
        self.explorer = explorer
        self.budget = budget
        self.clock = clock
        self.limit = daily_credit_limit

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
    ) -> WebSearchAnswer:
        if not query.strip():
            raise Invalid("A web search needs a query")
        if not 1 <= num_results <= MAX_SEARCH_RESULTS:
            raise Invalid(f"num_results is between 1 and {MAX_SEARCH_RESULTS}")
        # Context.dev charges a credit per ten results.
        tags = await self._start(project_id, session_id, ceil(num_results / 10))
        results = await self.explorer.search(
            query.strip(),
            num_results=num_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            country=country,
            languages=languages,
            tags=tags,
        )
        return WebSearchAnswer(results=results)

    async def read(
        self, project_id: Id, session_id: Id, url: str, max_chars: int = 20_000
    ) -> WebReadAnswer:
        if not url.strip().startswith(("http://", "https://")):
            raise Invalid("web_read reads an http(s) URL")
        if not 1 <= max_chars <= MAX_READ_CHARS:
            raise Invalid(f"max_chars is between 1 and {MAX_READ_CHARS}")
        tags = await self._start(project_id, session_id, 1)
        page = await self.explorer.read(url.strip(), tags=tags)
        return WebReadAnswer(
            url=page.url,
            title=page.title,
            markdown=page.markdown[:max_chars],
            truncated=len(page.markdown) > max_chars,
        )

    async def map(
        self,
        project_id: Id,
        session_id: Id,
        domain: str,
        search: str | None = None,
        max_links: int = 50,
    ) -> WebMapAnswer:
        if not domain.strip():
            raise Invalid("web_map needs a domain, e.g. thl.fi")
        if not 1 <= max_links <= MAX_MAP_LINKS:
            raise Invalid(f"max_links is between 1 and {MAX_MAP_LINKS}")
        tags = await self._start(project_id, session_id, 1)
        links = await self.explorer.map(
            domain.strip(), search=search or None, max_links=max_links, tags=tags
        )
        return WebMapAnswer(links=links)

    async def _start(self, project_id: Id, session_id: Id, credits: int) -> tuple[str, ...]:
        session = await self.sessions.get(session_id)
        if session.project_id != project_id:
            raise Invalid(f"Session {session_id} is not in project {project_id}")
        if not self.explorer.configured:
            raise Invalid(
                "The web tools need a Context.dev key: CONTEXT_DEV_API_KEY in the backend's "
                "environment (.env.local in development)"
            )
        day = self.clock.now().date()
        if not await self.budget.spend(project_id, day, credits, self.limit):
            raise Invalid(
                f"The web budget of this project ({self.limit} credits a day) is used up for today"
            )
        return ("ada", f"project:{project_id}")
