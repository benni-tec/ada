import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.agents import (
    AgentTurn,
    ModelList,
    PostedMessage,
    SourcePart,
    ToolPart,
    ToolState,
    TurnPart,
    TurnStatus,
)
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorKind
from ada.core.models.sessions import Context
from ada.core.ports.agents import (
    AgentFailed,
    AgentRuntime,
    AgentToolbox,
    LanguageModels,
    TurnProgress,
    TurnSink,
)
from ada.core.ports.events import EventBroadcaster, EventPublisher
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    AgentTurnRepository,
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.agents.briefing import Briefing
from ada.core.services.ports.agents import AgentTurnService
from ada.core.services.ports.sessions import SessionService

logger = logging.getLogger(__name__)

# Model requests per turn. Enough to look around, build a pipeline and a widget, and pin
# it; a turn that needs more is going in circles.
MAX_STEPS = 24


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
        runtime: AgentRuntime,
        language_models: LanguageModels,
        agent_settings: AgentSettingsRepository,
        events: EventPublisher,
        broadcaster: EventBroadcaster,
        after_commit: AfterCommit,
        dispatcher: TaskDispatcher,
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
        self.clock = clock
        self.briefing = Briefing(operators, dashboards, widgets, data_sources)

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
        chosen = model or catalog.session_agent
        if chosen is None:
            return PostedMessage(entry=entry)
        session = await self.sessions.get(session_id)
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
            await self.events.publish(self._finished(session.project_id, turn))
            return PostedMessage(entry=entry, turn=turn)
        await self.events.publish(
            self._event(EventType.AGENT_TURN_STARTED, session.project_id, turn)
        )

        async def queue() -> None:
            # After the commit, so the worker finds the turn it is given.
            try:
                await self.dispatcher.run_turn(turn.id)
            except Exception as error:
                logger.exception("Queueing agent turn %s failed", turn.id)
                failed = await self.progress.finish(
                    turn.id,
                    TurnStatus.FAILED,
                    (),
                    f"The turn could not be queued: {error}",
                    self.clock.now(),
                )
                await self.broadcaster.publish(self._finished(session.project_id, failed))

        self.after_commit.add(queue)
        return PostedMessage(entry=entry, turn=turn)

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
            session = await self.sessions.get(turn.session_id)
            await self.events.publish(self._finished(session.project_id, turn))
        return turn

    async def run(self, id: Id, toolbox: AgentToolbox) -> AgentTurn:
        turn = await self.turn_records.get(id)
        session = await self.sessions.get(turn.session_id)
        if turn.status is not TurnStatus.QUEUED or not await self.progress.start(id):
            # Cancelled before it started, or run already.
            return await self.turn_records.get(id)
        await self.broadcaster.publish(
            self._event(EventType.AGENT_TURN_STARTED, session.project_id, turn)
        )
        recorder = _Recorder(self, session.project_id, turn)
        status, error = TurnStatus.FAILED, None
        try:
            # The key is read now, so a key entered after the message was posted is used.
            target = await self.language_models.target(turn.model)
            request = await self.briefing.request(
                turn,
                target,
                await self.projects.get(session.project_id),
                session,
                await self.sessions.entries(session.id),
                await self.turn_records.list(session.id),
                MAX_STEPS,
                (await self.agent_settings.get()).instructions,
            )
            async with toolbox.connect(_agent(turn.model), session.id) as tools:
                status = await self.runtime.run(request, tools, recorder)
        except (AgentFailed, Invalid) as failure:
            # Invalid: the model was removed, or became unusable, since the message.
            error = str(failure)
        except Exception as failure:
            # Whatever went wrong, the turn must end: a turn left running would show a
            # spinner forever. The worker's log has the details.
            logger.exception("Agent turn %s failed", id)
            error = f"The turn failed unexpectedly: {type(failure).__name__}: {failure}"
        finished = await self.progress.finish(id, status, recorder.parts, error, self.clock.now())
        await self.broadcaster.publish(self._finished(session.project_id, finished))
        return finished

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


def _operators(output: Any) -> list[dict[str, Any]]:
    """Operator-shaped objects in a tool result: the result itself or the items of a list."""
    candidates = output if isinstance(output, list) else [output]
    return [
        item
        for item in candidates
        if isinstance(item, dict) and "kind" in item and "params" in item
    ]
