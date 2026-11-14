"""What the agent is told for one turn: the system prompt (ADA's model, the session, the
rules, what the message's context items mean) and the conversation so far."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from ada.core.models.actors import ActorKind
from ada.core.models.agents import (
    AgentTurn,
    HistoryMessage,
    ModelTarget,
    SourcePart,
    TextPart,
    ToolPart,
    ToolState,
    TurnRequest,
    TurnStatus,
)
from ada.core.models.base import Id
from ada.core.models.errors import NotFound
from ada.core.models.projects import Project
from ada.core.models.sessions import (
    Context,
    DashboardContext,
    EntryKind,
    PipelineContext,
    Session,
    SessionEntry,
    WidgetContext,
)
from ada.core.ports.repositories import (
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    WidgetRepository,
)
from ada.core.services.pipelines.listing import name as operator_name

# Older messages are left out: the record stays readable in the session, and the model's
# context window is not the place for all of it.
MAX_HISTORY = 40

ABOUT_ADA = """\
You are the analysis agent of ADA, a platform for traceable data analysis. You work with \
people inside the platform, in a session, using ADA's tools.

How ADA works:
- A project holds data sources, pipelines, sessions, dashboards, reports and alerts.
- A data source is registered once per project (address, format, freshness policy).
- A pipeline is a chain of operators. A source operator reads a data source; a transform \
is SQL over earlier operators, which it names input_0, input_1, ... in the order of its \
inputs; an input operator is a named slot. An operator's id is its definition: adding the \
same definition again returns the same operator.
- A run evaluates operators and fixes the snapshots of data it reads, so every number can \
be traced to its source and fetch time.
- A widget shows one operator's output (value, table, line-chart, map, or a Vega-Lite \
chart). It fetches its own data from the platform; you pass only the operator id, never \
numbers.
- A dashboard is a live view of widgets in named slots; every edit adds a version. A \
report freezes widgets at one run. Alert rules watch a measure on a dashboard.
"""

RULES = """\
Rules:
- Build on operators by their id. Prefer the project's existing pipelines \
(list_pipelines, get_lineage) to building new ones; build new steps on top of them.
- Never state a number you did not read from a tool result in this conversation. Prefer \
showing numbers in a widget to writing them in your answer.
- Give every widget a one-line note: what it shows and why.
- Pass the session id to tools that take a session_id, so your work is recorded in this \
session (it is filled in when you leave it out).
- Writes to dashboards need the revision you read with get_dashboard as \
expected_revision; on a conflict read again.
- When a tool refuses a call, read its message and correct the call; do not repeat it \
unchanged.
- Answer briefly, in the language of the message. Say what you built and where it is.
"""


class Briefing:
    """Builds the TurnRequest of a turn from the stored records."""

    def __init__(
        self,
        operators: OperatorRepository,
        dashboards: DashboardRepository,
        widgets: WidgetRepository,
        data_sources: DataSourceRepository,
    ) -> None:
        self.operators = operators
        self.dashboards = dashboards
        self.widgets = widgets
        self.data_sources = data_sources

    async def request(
        self,
        turn: AgentTurn,
        target: ModelTarget,
        project: Project,
        session: Session,
        entries: Sequence[SessionEntry],
        turns: Sequence[AgentTurn],
        max_steps: int,
    ) -> TurnRequest:
        # The record is in order, so what came before the message is what precedes it.
        position = next(i for i, entry in enumerate(entries) if entry.id == turn.prompt_entry_id)
        prompt_entry, earlier = entries[position], entries[:position]
        sections = [
            ABOUT_ADA,
            await self._session(project, session),
            RULES,
            await self._context(prompt_entry.context),
        ]
        return TurnRequest(
            model=turn.model,
            target=target,
            instructions="\n".join(section for section in sections if section),
            history=tuple(history(earlier, {t.id: t for t in turns})[-MAX_HISTORY:]),
            prompt=prompt_entry.text,
            max_steps=max_steps,
        )

    async def _session(self, project: Project, session: Session) -> str:
        lines = [
            "This session:",
            f'- Project "{project.name}", id {project.id}.',
            f'- Session "{session.title}", id {session.id}.',
        ]
        if session.origin_dashboard_id is not None:
            origin = await self._dashboard_name(session.origin_dashboard_id)
            lines.append(f"- It was started from the dashboard {origin}.")
        if session.panel_dashboard_id is not None:
            lines.append(
                f"- The dashboard {await self._dashboard_name(session.panel_dashboard_id)} "
                "is shown beside the conversation; the person sees your changes to it."
            )
        return "\n".join(lines) + "\n"

    async def _context(self, context: Sequence[Context]) -> str:
        if not context:
            return ""
        lines = ["The person attached these to the message:"]
        for item in context:
            lines.append(f"- {await self._describe(item)}")
        return "\n".join(lines) + "\n"

    async def _describe(self, item: Context) -> str:
        match item:
            case PipelineContext():
                return await self._pipeline(item)
            case DashboardContext():
                where = (
                    f'in its slot "{item.slot}"'
                    if item.slot
                    else "in a new slot named after what it shows"
                )
                return (
                    f"A dashboard: {await self._dashboard_name(item.dashboard_id)}. Put the "
                    f"widget you make for this message on it with pin_widget, {where}. Read "
                    "it with get_dashboard first for its revision."
                )
            case WidgetContext():
                return await self._widget(item)

    async def _pipeline(self, item: PipelineContext) -> str:
        try:
            operator = await self.operators.get(item.operator_id)
        except NotFound:
            return f"A pipeline, operator {item.operator_id}, which no longer exists."
        names = {
            source.id: source.name for source in await self.data_sources.list(operator.project_id)
        }
        columns = ", ".join(column.name for column in operator.output.columns) or "not known yet"
        return (
            f'A pipeline to build on: "{operator_name(operator, names)}", operator '
            f"{operator.id} ({operator.kind.value}; columns: {columns}). Use this operator as "
            "the input of your steps or the operator of your widget."
        )

    async def _widget(self, item: WidgetContext) -> str:
        try:
            widget = await self.widgets.get(item.widget_id)
        except NotFound:
            return f"A widget, {item.widget_id}, which no longer exists."
        return (
            f'A widget the person refers to: "{widget.title}", id {widget.id}, a '
            f"{widget.type} of operator {widget.operator_id}."
        )

    async def _dashboard_name(self, dashboard_id: Id) -> str:
        try:
            dashboard = await self.dashboards.get(dashboard_id)
        except NotFound:
            return f"{dashboard_id} (no longer exists)"
        return f'"{dashboard.name}", id {dashboard.id}'


def history(entries: Sequence[SessionEntry], turns: Mapping[Id, AgentTurn]) -> list[HistoryMessage]:
    """The conversation as the model sees it: people's messages, and the agent's earlier
    answers with their tool calls summarised. Steps other clients recorded in the session
    are noted, so the agent knows what is already there."""
    messages: list[HistoryMessage] = []
    for entry in entries:
        match entry.kind:
            case EntryKind.MESSAGE:
                messages.append(HistoryMessage(role="user", text=entry.text))
            case EntryKind.AGENT_TURN:
                turn = turns.get(_id(entry.ref)) if entry.ref else None
                if turn is not None and (answer := summary(turn)):
                    messages.append(HistoryMessage(role="assistant", text=answer))
            case EntryKind.OPERATOR | EntryKind.WIDGET if entry.actor.kind is not ActorKind.AGENT:
                # The agent's own steps are in its answers already.
                what = "an operator" if entry.kind is EntryKind.OPERATOR else "a widget"
                note = f": {entry.text}" if entry.text else ""
                messages.append(
                    HistoryMessage(
                        role="user",
                        text=f"[{entry.actor.name} added {what}, {entry.ref}{note}]",
                    )
                )
            case _:
                pass
    return messages


def summary(turn: AgentTurn) -> str:
    """An earlier answer: its text, with a line per tool call saying what it made."""
    lines: list[str] = []
    for part in turn.parts:
        match part:
            case TextPart() if part.text.strip():
                lines.append(part.text.strip())
            case ToolPart():
                lines.append(_tool_line(part))
            case SourcePart():
                lines.append(f"[read data source {part.title}, {part.source_id}]")
            case _:
                pass
    if turn.status is TurnStatus.FAILED and turn.error:
        lines.append(f"[this answer failed: {turn.error}]")
    elif turn.status is TurnStatus.CANCELLED:
        lines.append("[this answer was cancelled]")
    return "\n".join(lines)


def _tool_line(part: ToolPart) -> str:
    if part.state is ToolState.OUTPUT_ERROR:
        return f"[called {part.tool_name}: failed, {part.error_text}]"
    made = _made(part.output)
    return f"[called {part.tool_name}{f': {made}' if made else ''}]"


def _made(output: Any) -> str:
    """The id of what a tool call returned, which is what a later turn builds on."""
    if not isinstance(output, dict):
        return ""
    for key in ("widget", "dashboard", "report", "session", "rule"):
        if isinstance(output.get(key), dict) and "id" in output[key]:
            return f"{key} {output[key]['id']}"
    if "id" in output:
        return str(output["id"])
    return ""


def _id(ref: str) -> Id | None:
    try:
        return UUID(ref)
    except ValueError:
        return None
