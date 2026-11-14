"""Research delegated to the research agent: a child session in which it looks for data,
adds what it finds as sources, and reports back into the session that delegated.

The research agent runs on whatever model is configured for it; nothing here depends on
the provider. Its turns are AgentTurns' like any other, with their own briefing, tools and
step limit; how a turn that did not report back ends is posted there too."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar

from ada.core.models.actors import Actor
from ada.core.models.agents import ResearchLimits
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.sessions import Session, SessionEntry
from ada.core.models.web import Monitor, PageText
from ada.core.ports.agents import LanguageModels, ResearchCalls
from ada.core.ports.repositories import DataSourceRepository, SessionRepository
from ada.core.ports.web import PageReader
from ada.core.services.ports.agents import AgentTurnService, ResearchService
from ada.core.services.ports.sessions import SessionService

# The research session whose turn runs in this task. AgentTurns sets it around the turn's
# tools, whose calls run in tasks that copy it (as ada.entrypoints.mcp.actor's agent), so
# whatever session a tool call names, its paid web calls count against this one.
_researching: ContextVar[Id | None] = ContextVar("researching", default=None)


@contextmanager
def researching(session_id: Id) -> Iterator[None]:
    token = _researching.set(session_id)
    try:
        yield
    finally:
        _researching.reset(token)


async def count_web_call(calls: ResearchCalls, cap: int, session_id: Id | None) -> None:
    """ResearchService.use_web_call."""
    # Not through the call's own unit of work: see ResearchCalls.
    session_id = _researching.get() or session_id
    if session_id is not None and not await calls.use(session_id, cap):
        raise Invalid(
            f"This research session has used its {cap} web calls; "
            "call report_back with what you have"
        )


class ResearchPages(PageReader):
    """The pages document sources read, each read counted like a web call when a research
    turn makes it: previewing a document source it added, for one. A refresh it queues
    runs in the worker, outside the turn, and is counted when queued; later refreshes are
    not the research's."""

    def __init__(self, pages: PageReader, calls: ResearchCalls, limits: ResearchLimits) -> None:
        self.pages = pages
        self.calls = calls
        self.limits = limits

    async def read(self, url: str) -> PageText:
        await count_web_call(self.calls, self.limits.web_calls, None)
        return await self.pages.read(url)

    async def extract(self, url: str, instruction: str, columns: Sequence[str]) -> list[JsonObject]:
        await count_web_call(self.calls, self.limits.web_calls, None)
        return await self.pages.extract(url, instruction, columns)

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        return await self.pages.watch(url, webhook_url)

    async def unwatch(self, monitor_id: str) -> None:
        await self.pages.unwatch(monitor_id)


class Research(ResearchService):
    def __init__(
        self,
        turns: AgentTurnService,
        session_records: SessionService,
        sessions: SessionRepository,
        data_sources: DataSourceRepository,
        language_models: LanguageModels,
        calls: ResearchCalls,
        limits: ResearchLimits,
    ) -> None:
        self.turns = turns
        self.session_records = session_records
        self.sessions = sessions
        self.data_sources = data_sources
        self.language_models = language_models
        self.calls = calls
        self.limits = limits

    async def delegate(
        self, parent_session_id: Id, brief: str, title: str, actor: Actor
    ) -> Session:
        model = await self.language_models.research_agent()
        if model is None:
            raise Invalid("No research agent model is configured")
        if not brief.strip():
            raise Invalid("A research brief needs text")
        child = await self.session_records.create_research(parent_session_id, title, actor)
        await self.turns.post_message(child.id, brief, actor, model=model)
        return child

    async def report(
        self,
        child_session_id: Id,
        summary: str,
        source_ids: Sequence[Id],
        missing: Sequence[str],
        actor: Actor,
    ) -> SessionEntry:
        child = await self.sessions.get(child_session_id)
        if not summary.strip():
            raise Invalid("A report needs a summary")
        sections = [summary.strip()]
        added = []
        for source_id in dict.fromkeys(source_ids):
            source = await self.data_sources.get(source_id)
            if source.project_id != child.project_id:
                raise Invalid(f"The source {source_id} belongs to another project")
            added.append(f"- {source.name}, source {source.id}")
        if added:
            sections.append("Sources added:\n" + "\n".join(added))
        gaps = [f"- {item.strip()}" for item in missing if item.strip()]
        if gaps:
            sections.append("Not found:\n" + "\n".join(gaps))
        posted = await self.turns.post_report(child.id, "\n\n".join(sections), actor)
        return posted.entry

    async def use_web_call(self, session_id: Id | None = None) -> None:
        await count_web_call(self.calls, self.limits.web_calls, session_id)
