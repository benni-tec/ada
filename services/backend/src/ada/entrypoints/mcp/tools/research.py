from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id
from ada.core.models.sessions import Session, SessionEntry
from ada.core.services.ports.agents import ResearchService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def delegate_research(
        brief: str, title: str, session_id: Id, research: FromDishka[ResearchService]
    ) -> Session:
        """Hand a research question to the research agent when the project lacks the data
        it needs. `brief` says what data to find (the measure, the population, the regions
        and years), `title` names the research in a few words. The research agent works in
        a child session of this one: it searches the web, adds the datasets it finds as
        sources and checks they load. This returns at once with the child session; its
        report comes back into this session later, and you continue from it."""
        return await research.delegate(session_id, brief, title, calling_agent())

    @mcp.tool
    @inject
    async def report_back(
        summary: str,
        source_ids: Sequence[Id],
        missing: Sequence[str],
        session_id: Id,
        research: FromDishka[ResearchService],
    ) -> SessionEntry:
        """End the research with your report to the session that delegated it. `summary`
        says what you found, in a few sentences; `source_ids` are the sources you added and
        checked (empty when none); `missing` lists what does not exist or could not be
        found, each with where you looked (empty when nothing is missing). Each call posts
        a new report."""
        return await research.report(session_id, summary, source_ids, missing, calling_agent())
