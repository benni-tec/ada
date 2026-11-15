"""Analysis delegated to the analyst: a child session in which an agent analyses data the
project already has, with statistics and transforms, and reports findings into the session
that delegated.

What keeps it provable: every finding names the operator whose output shows it. When the
report is posted, the platform reads every cited operator in one new run and refuses a
figure that is not in that output, in the finding, the summary or a caveat. The posted
report names the run and, per finding, the operator and the snapshots it rests on (source,
fetch time, content hash), so each number traces back like a widget's."""

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation

from ada.core.models.actors import Actor
from ada.core.models.agents import Finding
from ada.core.models.analysis import Rows
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.operators import Operator, OperatorId
from ada.core.models.runs import Run
from ada.core.models.schema import OutputKind
from ada.core.models.sessions import Session, SessionAgent, SessionEntry
from ada.core.ports.agents import LanguageModels
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    SessionRepository,
    SnapshotRepository,
)
from ada.core.services.pipelines import listing
from ada.core.services.ports.agents import (
    MAX_EVIDENCE_ROWS,
    AgentTurnService,
    AnalysisService,
)
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.reports.sources import SourcesList

# A figure as written in prose: digits with an optional decimal part and thousands commas,
# not part of a word or an id (op_3f2…). The sign is left out: "fell by 1.5" cites -1.5.
# A figure as written: thousands separators, decimals and an exponent belong to it.
_FIGURE = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+(?![\d])|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?")
# An ISO date is one figure, matched against date cells (and dates written in text cells).
_DATE = re.compile(r"(?<![\w.-])\d{4}-\d{2}-\d{2}(?![\w])")
_EXACT = Context(prec=200)


class Analysis(AnalysisService):
    def __init__(
        self,
        turns: AgentTurnService,
        session_records: SessionService,
        sessions: SessionRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        data_sources: DataSourceRepository,
        runs: RunService,
        language_models: LanguageModels,
    ) -> None:
        self.turns = turns
        self.session_records = session_records
        self.sessions = sessions
        self.operators = operators
        self.data_sources = data_sources
        self.runs = runs
        self.language_models = language_models
        self.sources_list = SourcesList(operators, snapshots, data_sources)

    async def delegate(
        self,
        parent_session_id: Id,
        brief: str,
        title: str,
        operator_ids: Sequence[OperatorId],
        actor: Actor,
    ) -> Session:
        if (await self.language_models.catalog()).agent_for(SessionAgent.ANALYSIS) is None:
            raise Invalid("No session agent model is configured; the analyst runs on it")
        if not brief.strip():
            raise Invalid("An analysis brief needs text")
        parent = await self.sessions.get(parent_session_id)
        names = await self._source_names(parent.project_id)
        listed = []
        for operator_id in dict.fromkeys(operator_ids):
            operator = await self._operator(operator_id, parent.project_id)
            listed.append(f"- {operator.id}: {listing.name(operator, names)}")
        child = await self.session_records.create_child(
            parent_session_id, title, SessionAgent.ANALYSIS, actor
        )
        text = brief.strip()
        if listed:
            text += "\n\nOperators to analyse:\n" + "\n".join(listed)
        await self.turns.post_message(child.id, text, actor)
        return child

    async def report(
        self,
        child_session_id: Id,
        summary: str,
        findings: Sequence[Finding],
        caveats: Sequence[str],
        not_shown: Sequence[str],
        actor: Actor,
    ) -> SessionEntry:
        child = await self.sessions.get(child_session_id)
        if child.agent is not SessionAgent.ANALYSIS:
            raise Invalid("Only an analysis session reports findings")
        if not summary.strip():
            raise Invalid("A report needs a summary")
        caveats = [item.strip() for item in caveats if item.strip()]
        run = await self.runs.start(child.project_id, actor)
        cited: dict[OperatorId, tuple[Operator, Rows]] = {}
        problems: list[str] = []
        for number, finding in enumerate(findings, 1):
            if not finding.claim.strip():
                problems.append(f"Finding {number} has no claim")
                continue
            if finding.operator_id not in cited:
                operator = await self._operator(finding.operator_id, child.project_id)
                rows = await self.runs.read(run.id, operator.id, MAX_EVIDENCE_ROWS)
                cited[operator.id] = (operator, rows)
            operator, rows = cited[finding.operator_id]
            if missing := unsupported(finding.claim, [rows]):
                problems.append(
                    f"Finding {number}: {', '.join(missing)} not in the output of "
                    f"{operator.id}{_cut_note(rows)}"
                )
        evidence = [rows for _, rows in cited.values()]
        not_shown = [item.strip() for item in not_shown if item.strip()]
        for label, text in (
            [("The summary", summary)]
            + [(f"Caveat {number}", caveat) for number, caveat in enumerate(caveats, 1)]
            + [(f"Could not show {number}", item) for number, item in enumerate(not_shown, 1)]
        ):
            if missing := unsupported(text, evidence):
                problems.append(f"{label}: {', '.join(missing)} not in any cited output")
        if problems:
            raise Invalid(
                "Not reported. Every figure must be in the output of a cited operator, as "
                "read in a new run:\n- "
                + "\n- ".join(problems)
                + "\nCompute the figure with a transform or statistic and cite it, write it "
                "as that output has it, or leave it out."
            )
        # The run as it now stands: reading fixed the snapshots it used.
        run = await self.runs.get(run.id)
        text = await self._text(run, summary.strip(), findings, cited, caveats, not_shown)
        posted = await self.turns.post_report(child.id, text, actor)
        return posted.entry

    async def _text(
        self,
        run: Run,
        summary: str,
        findings: Sequence[Finding],
        cited: dict[OperatorId, tuple[Operator, Rows]],
        caveats: Sequence[str],
        not_shown: Sequence[str],
    ) -> str:
        sections = [summary]
        if findings:
            names = await self._source_names(run.project_id)
            lines = [f"Findings, every figure checked against run {run.id}:"]
            for number, finding in enumerate(findings, 1):
                operator, _ = cited[finding.operator_id]
                lines.append(f"{number}. {finding.claim.strip()}")
                lines.append(
                    f"   Shown by {operator.kind.value} {operator.id}: "
                    f"{listing.name(operator, names)}"
                )
                for source in await self.sources_list.of_operator(run, operator.id):
                    fetched = (
                        f"fetched {source.fetched_at:%Y-%m-%d %H:%M} UTC"
                        if source.fetched_at
                        else "not fetched in this run"
                    )
                    content = f", content {source.content_hash[:12]}" if source.content_hash else ""
                    lines.append(f"   Data: {source.name}, {fetched}{content}")
            sections.append("\n".join(lines))
        if caveats:
            sections.append("Caveats:\n" + "\n".join(f"- {item}" for item in caveats))
        gaps = [f"- {item.strip()}" for item in not_shown if item.strip()]
        if gaps:
            sections.append("Could not show:\n" + "\n".join(gaps))
        return "\n\n".join(sections)

    async def _operator(self, operator_id: OperatorId, project_id: Id) -> Operator:
        try:
            operator = await self.operators.get(operator_id)
        except NotFound:
            raise Invalid(f"Operator {operator_id} does not exist") from None
        if operator.project_id != project_id:
            raise Invalid(f"Operator {operator_id} belongs to another project")
        if operator.output.kind is not OutputKind.TABLE:
            raise Invalid(f"Operator {operator_id} has no table output to analyse")
        return operator

    async def _source_names(self, project_id: Id) -> dict[Id, str]:
        return {source.id: source.name for source in await self.data_sources.list(project_id)}


def unsupported(text: str, evidence: Sequence[Rows]) -> list[str]:
    """The figures in `text` that no cell of `evidence` holds, as written. A figure matches a
    value that rounds (half up, either sign) to it at its written precision; an ISO date
    matches a date cell of that day, and a year any date in it; a text cell contributes the
    figures and dates written in it."""
    numbers: set[Decimal] = set()
    days: set[str] = set()
    for rows in evidence:
        for row in rows.rows:
            for cell in row:
                _collect(cell, numbers, days)
    missing: list[str] = []
    for found in _DATE.finditer(text):
        if found.group() not in days and found.group() not in missing:
            missing.append(found.group())
    for found in _FIGURE.finditer(_DATE.sub(" ", text)):
        written = found.group()
        if not _held(written, numbers) and written not in missing:
            missing.append(written)
    return missing


def _held(written: str, numbers: set[Decimal]) -> bool:
    figure = Decimal(written.replace(",", ""))
    step = Decimal(1).scaleb(figure.as_tuple().exponent)  # type: ignore[arg-type]
    for number in numbers:
        try:
            if number.quantize(step, ROUND_HALF_UP, _EXACT) == figure:
                return True
        except InvalidOperation:
            continue
    return False


def _collect(cell: object, numbers: set[Decimal], days: set[str]) -> None:
    match cell:
        case bool() | None:
            return
        case int() | Decimal():
            if Decimal(cell).is_finite():
                numbers.add(abs(Decimal(cell)))
        case float():
            if Decimal(repr(cell)).is_finite():
                numbers.add(abs(Decimal(repr(cell))))
        case datetime() | date():
            days.add(cell.isoformat()[:10])
            numbers.add(Decimal(cell.year))
        case str():
            for day in _DATE.findall(cell):
                days.add(day)
                numbers.add(Decimal(day[:4]))
            for found in _FIGURE.finditer(_DATE.sub(" ", cell)):
                numbers.add(Decimal(found.group().replace(",", "")))
        case _:
            return


def _cut_note(rows: Rows) -> str:
    if not rows.truncated:
        return ""
    return f" (only its first {MAX_EVIDENCE_ROWS} rows were read: cite a smaller output)"
