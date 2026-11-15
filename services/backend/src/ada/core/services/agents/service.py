import asyncio
import logging
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.agents import (
    AgentTurn,
    ModelList,
    PostedMessage,
    SourcePart,
    TextPart,
    ToolPart,
    ToolSpec,
    ToolState,
    TurnPart,
    TurnStatus,
)
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorKind
from ada.core.models.sessions import Context, EntryKind, Session, SessionAgent, SessionEntry
from ada.core.ports.agents import (
    AgentFailed,
    AgentRuntime,
    AgentToolbox,
    AgentTools,
    LanguageModels,
    TurnProgress,
    TurnSink,
)
from ada.core.ports.events import EventBroadcaster, EventPublisher
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    AgentTurnRepository,
    AlertRepository,
    AttachmentRepository,
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    ReportRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit, UnitsOfWork
from ada.core.services.agents.briefing import Briefing
from ada.core.services.agents.research import researching
from ada.core.services.ports.agents import AgentTurnService
from ada.core.services.ports.sessions import SessionService

logger = logging.getLogger(__name__)

# Model requests per turn. Enough to look around, build a pipeline and a widget, and pin
# it; a turn that needs more is going in circles.
MAX_STEPS = 24
# A research turn searches, reads pages and checks each source it adds.
MAX_RESEARCH_STEPS = 60
# An analysis turn profiles, computes and checks before it reports.
MAX_ANALYSIS_STEPS = 40

# How long a turn may run. One that takes longer is going in circles or waiting on
# something that does not answer; it fails, and the session's next turn can start.
TURN_TIME_LIMIT = timedelta(minutes=30)
# The turns of a session run one after the other: a turn waits for the earlier ones,
# looking every WAIT_POLL seconds. A turn that holds the session up for longer than a turn
# may run, plus TURN_MARGIN, ended without saying so (its worker stopped, or its task was
# lost), and is failed so that the session goes on. `recover` fails one that nothing waits
# for, measured from when it started.
WAIT_POLL = 1.0
TURN_MARGIN = timedelta(minutes=1)
ABANDONED = "The turn did not end in time; the worker running it has probably stopped"

INCOMPLETE = "(incomplete: ended without a report)"
UNCHECKED = (
    "The analysis ended without a checked report, so none of its figures are passed on. "
    "Its session has its work."
)


class AgentTurns(AgentTurnService):
    """Queues a turn for every message when a session agent is configured, and runs it.

    Queueing happens in the message's unit of work like any other write. Running does not:
    the turn's progress is written through TurnProgress, each step committed at once, and
    its events are broadcast right after those commits rather than through the
    transactional publisher. Parts are broadcast as they happen, before anything is stored,
    which is the one documented exception to "events after the commit".
    """

    def __init__(
        self,
        turns: AgentTurnRepository,
        progress: TurnProgress,
        sessions: SessionRepository,
        session_records: SessionService,
        projects: ProjectRepository,
        operators: OperatorRepository,
        dashboards: DashboardRepository,
        widgets: WidgetRepository,
        data_sources: DataSourceRepository,
        attachments: AttachmentRepository,
        alerts: AlertRepository,
        reports: ReportRepository,
        runtime: AgentRuntime,
        language_models: LanguageModels,
        agent_settings: AgentSettingsRepository,
        events: EventPublisher,
        broadcaster: EventBroadcaster,
        after_commit: AfterCommit,
        dispatcher: TaskDispatcher,
        units: UnitsOfWork,
        clock: Clock,
    ) -> None:
        self.turn_records = turns
        self.progress = progress
        self.sessions = sessions
        self.session_records = session_records
        self.projects = projects
        self.data_sources = data_sources
        self.runtime = runtime
        self.language_models = language_models
        self.agent_settings = agent_settings
        self.events = events
        self.broadcaster = broadcaster
        self.after_commit = after_commit
        self.dispatcher = dispatcher
        self.units = units
        self.clock = clock
        self.briefing = Briefing(
            operators, dashboards, widgets, data_sources, attachments, alerts, reports
        )

    async def models(self) -> ModelList:
        return await self.language_models.catalog()

    async def post_message(
        self,
        session_id: Id,
        text: str,
        actor: Actor,
        context: Sequence[Context] = (),
        model: str | None = None,
    ) -> PostedMessage:
        catalog = await self.language_models.catalog()
        if model is not None and all(known.id != model for known in catalog.models):
            known = ", ".join(info.id for info in catalog.models) or "none"
            raise Invalid(f"No model {model!r} is configured (configured: {known})")
        entry = await self.session_records.add_message(session_id, text, actor, context)
        session = await self.sessions.get(session_id)
        return PostedMessage(entry=entry, turn=await self._queue(session, entry, catalog, model))

    async def post_report(self, child_session_id: Id, text: str, actor: Actor) -> PostedMessage:
        entry = await self.session_records.record_report(child_session_id, text, actor)
        parent = await self.sessions.get(entry.session_id)
        delegation = next(
            (
                other
                for other in await self.sessions.entries(parent.id)
                if other.kind is EntryKind.DELEGATION and other.ref == str(child_session_id)
            ),
            None,
        )
        # The session agent delegated and acts on the report; a person reads it.
        if delegation is None or delegation.actor.kind is not ActorKind.AGENT:
            return PostedMessage(entry=entry)
        catalog = await self.language_models.catalog()
        return PostedMessage(entry=entry, turn=await self._queue(parent, entry, catalog))

    async def wait(self, id: Id) -> None:
        # Measured from when this turn first saw the one ahead in its current state, which
        # is no earlier than when that one started: one still running then has run longer
        # than its own time limit. One still queued with nothing ahead of it was lost.
        holder: tuple[Id, TurnStatus] | None = None
        since = self.clock.now()
        while (ahead := await self._ahead(id)) is not None:
            if (ahead.id, ahead.status) != holder:
                holder, since = (ahead.id, ahead.status), self.clock.now()
            elif self.clock.now() - since > TURN_TIME_LIMIT + TURN_MARGIN:
                await self._abandon(ahead)
                continue
            await asyncio.sleep(WAIT_POLL)

    async def ended(self, id: Id) -> None:
        if not await self.turn_records.settle(id):
            return
        turn = await self.turn_records.get(id)
        session = await self.sessions.get(turn.session_id)
        await self.events.publish(self._finished(session.project_id, turn))
        # A report that fails raises on and rolls the settling back: the recovery retries.
        await self._report_end(session, turn)

    async def recover(self) -> None:
        now = self.clock.now()
        stuck = await self.turn_records.unsettled(
            now - TURN_TIME_LIMIT - TURN_MARGIN, now - TURN_MARGIN
        )
        for turn in stuck:
            if turn.status is TurnStatus.RUNNING:
                await self._abandon(turn)
            else:
                await self._ended_apart(turn.id)

    async def _ahead(self, id: Id) -> AgentTurn | None:
        """The earliest turn of the session before this one that has not ended. None when
        there is none, or when this one is no longer queued (cancelled, or run already)."""
        ahead = None
        for turn in await self.progress.session_turns(id):
            if turn.id == id:
                return ahead if turn.status is TurnStatus.QUEUED else None
            if ahead is None and turn.status in (TurnStatus.QUEUED, TurnStatus.RUNNING):
                ahead = turn
        return None

    async def _abandon(self, turn: AgentTurn) -> None:
        logger.warning("Agent turn %s did not end in time; failing it", turn.id)
        if await self.progress.abandon(turn.id, ABANDONED, self.clock.now()) is not None:
            await self._ended_apart(turn.id)

    async def _ended_apart(self, id: Id) -> None:
        """`ended`, in a unit of work of its own: the caller's has committed already, or
        runs on for the length of a turn."""
        try:
            await self.units.run(AgentTurnService, lambda turns: turns.ended(id))
        except Exception:
            logger.exception("Announcing the end of agent turn %s failed", id)

    async def _queue(
        self, session: Session, entry: SessionEntry, catalog: ModelList, model: str | None = None
    ) -> AgentTurn | None:
        """The agent's turn on an entry of the session's record, queued once this commits.
        None when no model answers in the session."""
        chosen = model or catalog.agent_for(session.agent)
        if chosen is None:
            return None
        session_id = session.id
        info = next(info for info in catalog.models if info.id == chosen)
        turn = AgentTurn(
            id=uuid7(),
            session_id=session_id,
            prompt_entry_id=entry.id,
            model=chosen,
            created_at=self.clock.now(),
        )
        if not info.available:
            # Said at once, in the conversation, rather than by a task that cannot run.
            turn = turn.model_copy(
                update={
                    "status": TurnStatus.FAILED,
                    "error": info.reason or "The model cannot be used",
                    "finished_at": self.clock.now(),
                }
            )
        await self.turn_records.add(turn)
        await self.session_records.record_agent_turn(session_id, turn.id, _agent(chosen))
        if turn.status is TurnStatus.FAILED:
            await self.ended(turn.id)
            return turn
        await self.events.publish(
            self._event(EventType.AGENT_TURN_STARTED, session.project_id, turn)
        )

        async def queue() -> None:
            # After the commit, so the worker finds the turn it is given.
            try:
                await self.dispatcher.run_turn(turn.id)
            except Exception as error:
                logger.exception("Queueing agent turn %s failed", turn.id)
                message = f"The turn could not be queued: {error}"
                await self.progress.abandon(turn.id, message, self.clock.now())
                await self._ended_apart(turn.id)

        self.after_commit.add(queue)
        return turn

    async def turns(self, session_id: Id) -> Sequence[AgentTurn]:
        await self.sessions.get(session_id)
        return await self.turn_records.list(session_id)

    async def get(self, id: Id) -> AgentTurn:
        return await self.turn_records.get(id)

    async def cancel(self, id: Id) -> AgentTurn:
        before = await self.turn_records.get(id)
        turn = await self.turn_records.request_cancel(id, self.clock.now())
        if before.status is TurnStatus.QUEUED and turn.status is TurnStatus.CANCELLED:
            # A running turn announces its own end when it stops.
            await self.ended(turn.id)
        return turn

    async def run(self, id: Id, toolbox: AgentToolbox) -> AgentTurn:
        turn = await self.turn_records.get(id)
        session = await self.sessions.get(turn.session_id)
        started = turn.status is TurnStatus.QUEUED and await self.progress.start(
            id, self.clock.now()
        )
        if not started:
            # Cancelled before it started, or run already.
            return await self.turn_records.get(id)
        await self.broadcaster.publish(
            self._event(EventType.AGENT_TURN_STARTED, session.project_id, turn)
        )
        recorder = _Recorder(self, session.project_id, turn)
        status, error = TurnStatus.FAILED, None
        deadline = asyncio.timeout(TURN_TIME_LIMIT.total_seconds())
        try:
            async with deadline:
                # The key is read now, so a key entered after the message was posted is used.
                target = await self.language_models.target(turn.model)
                research = session.agent is SessionAgent.RESEARCH
                request = await self.briefing.request(
                    turn,
                    target,
                    await self.projects.get(session.project_id),
                    session,
                    await self.sessions.entries(session.id),
                    await self.turn_records.list(session.id),
                    _steps(session.agent),
                    (await self.agent_settings.get()).instructions,
                )
                agent = _agent(turn.model)
                # Paid web calls in a research turn count against its session.
                with researching(session.id) if research else nullcontext():
                    async with toolbox.connect(agent, session.id, session.agent) as tools:
                        fenced = _Fenced(tools, self.progress, id)
                        status = await self.runtime.run(request, fenced, recorder)
        except (AgentFailed, Invalid) as failure:
            # Invalid: the model was removed, or became unusable, since the message.
            error = str(failure)
        except Exception as failure:
            if isinstance(failure, TimeoutError) and deadline.expired():
                minutes = TURN_TIME_LIMIT.total_seconds() / 60
                error = f"The turn did not finish within {minutes:g} minutes"
            else:
                # Whatever went wrong, the turn must end: a turn left running would show a
                # spinner forever. The worker's log has the details.
                logger.exception("Agent turn %s failed", id)
                error = f"The turn failed unexpectedly: {type(failure).__name__}: {failure}"
        finished = await self.progress.finish(id, status, recorder.parts, error, self.clock.now())
        if finished is None:
            # Failed meanwhile, as if its worker had stopped; that ending was announced.
            logger.warning("Agent turn %s was failed while it still ran", id)
            return await self.turn_records.get(id)
        # Before settling, so that a broadcast that fails leaves the turn to the recovery.
        # Settling announces it again: clients take a second finished event as the first.
        await self.broadcaster.publish(self._finished(session.project_id, finished))
        # Apart, so that a report that fails is not committed as settled with this task:
        # the recovery retries it.
        await self._ended_apart(id)
        return finished

    async def _report_end(self, session: Session, turn: AgentTurn) -> None:
        """The delegated turn on the brief, when it did not report back, reports how it
        ended: its final text, marked incomplete, or its failure. Only whoever settles the
        turn calls this, in the same unit of work, so it happens once. A person's follow-ups
        in the research session are a conversation of their own: they report only by
        calling report_back."""
        parent_id = session.parent_session_id
        if session.agent is SessionAgent.SESSION or parent_id is None:
            return
        entries = await self.sessions.entries(session.id)
        brief = next((entry for entry in entries if entry.kind is EntryKind.MESSAGE), None)
        if brief is None or turn.prompt_entry_id != brief.id:
            return
        # The parent's record says whether it reported, not the turn's parts: report_back
        # commits its report before the turn stores the call's result.
        if any(
            entry.kind is EntryKind.REPORT and entry.ref == str(session.id)
            for entry in await self.sessions.entries(parent_id)
        ):
            return
        if turn.status is TurnStatus.DONE and session.agent is SessionAgent.ANALYSIS:
            # Its final text was never checked against the data, so it is not passed on.
            text = UNCHECKED
        elif turn.status is TurnStatus.DONE:
            text = f"{_final_text(turn) or 'It gave no answer.'}\n\n{INCOMPLETE}"
        elif turn.status is TurnStatus.FAILED:
            what = "Research" if session.agent is SessionAgent.RESEARCH else "Analysis"
            text = f"{what} failed: {turn.error}"
        else:
            # Cancelled by a person, who knows.
            return
        await self.post_report(session.id, text, _agent(turn.model))

    def _finished(self, project_id: Id, turn: AgentTurn) -> Event:
        return self._event(
            EventType.AGENT_TURN_FINISHED, project_id, turn, {"status": turn.status.value}
        )

    def _event(
        self,
        type: EventType,
        project_id: Id,
        turn: AgentTurn,
        extra: dict[str, Any] | None = None,
    ) -> Event:
        return Event(
            type=type,
            project_id=project_id,
            payload={"session_id": str(turn.session_id), "turn_id": str(turn.id)} | (extra or {}),
            at=self.clock.now(),
        )

    async def _sources(self, project_id: Id, output: Any, seen: set[Id]) -> list[SourcePart]:
        """The data sources a tool result shows the agent reading: source operators in it
        (add_source_operator, get_lineage). Each is shown once per turn."""
        found: list[SourcePart] = []
        for operator in _operators(output):
            if operator.get("kind") != OperatorKind.SOURCE.value:
                continue
            try:
                source_id = UUID(str(operator.get("params", {}).get("data_source_id")))
                source = await self.data_sources.get(source_id)
            except ValueError, NotFound:
                continue
            if source.id in seen or source.project_id != project_id:
                continue
            seen.add(source.id)
            url = source.address if source.address.startswith(("http://", "https://")) else None
            found.append(SourcePart(source_id=source.id, title=source.name, url=url))
        return found


class _Fenced(AgentTools):
    """A turn's tools, refused once the turn no longer runs: it was failed while its worker
    was only slow, and another turn of the session may be running by now."""

    def __init__(self, tools: AgentTools, progress: TurnProgress, id: Id) -> None:
        self.tools = tools
        self.progress = progress
        self.id = id

    def specs(self) -> Sequence[ToolSpec]:
        return self.tools.specs()

    async def call(self, name: str, arguments: JsonObject) -> Any:
        if not await self.progress.running(self.id):
            raise AgentFailed("The turn was ended while it ran")
        return await self.tools.call(name, arguments)


class _Recorder(TurnSink):
    """The parts of one running turn: published as they change, stored at each step."""

    def __init__(self, service: AgentTurns, project_id: Id, turn: AgentTurn) -> None:
        self.service = service
        self.project_id = project_id
        self.turn = turn
        self.parts: list[TurnPart] = []
        self.seen_sources: set[Id] = set()

    async def add(self, part: TurnPart) -> int:
        self.parts.append(part)
        index = len(self.parts) - 1
        await self._publish(index)
        return index

    async def replace(self, index: int, part: TurnPart) -> None:
        self.parts[index] = part
        await self._publish(index)
        if isinstance(part, ToolPart) and part.state is ToolState.OUTPUT_AVAILABLE:
            sources = await self.service._sources(self.project_id, part.output, self.seen_sources)
            for source in sources:
                await self.add(source)

    async def checkpoint(self) -> bool:
        return await self.service.progress.checkpoint(self.turn.id, self.parts)

    async def _publish(self, index: int) -> None:
        event = self.service._event(
            EventType.AGENT_TURN_PART,
            self.project_id,
            self.turn,
            {"index": index, "part": self.parts[index].model_dump(mode="json")},
        )
        # At once, not after a commit: a token that is not sent now is never seen live.
        await self.service.broadcaster.publish(event)


def _agent(model: str) -> Actor:
    return Actor(kind=ActorKind.AGENT, name=model)


def _final_text(turn: AgentTurn) -> str:
    texts = [part.text.strip() for part in turn.parts if isinstance(part, TextPart)]
    return next((text for text in reversed(texts) if text), "")


def _operators(output: Any) -> list[dict[str, Any]]:
    """Operator-shaped objects in a tool result: the result itself or the items of a list."""
    candidates = output if isinstance(output, list) else [output]
    return [
        item
        for item in candidates
        if isinstance(item, dict) and "kind" in item and "params" in item
    ]


def _steps(agent: SessionAgent) -> int:
    match agent:
        case SessionAgent.RESEARCH:
            return MAX_RESEARCH_STEPS
        case SessionAgent.ANALYSIS:
            return MAX_ANALYSIS_STEPS
        case _:
            return MAX_STEPS
