from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.agents import Finding
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import Session, SessionEntry
from ada.core.services.ports.agents import MAX_EVIDENCE_ROWS, AnalysisService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId

REPORT_FINDINGS = f"""End the analysis with your report to the session that delegated it.
`summary` answers the question in a few sentences. `findings`, most important
first, are each one plain sentence (`claim`) and the operator whose output shows
it (`operator_id`). `caveats` are the assumptions and limits a reader must know;
`not_shown` what the data cannot show, each with why.

The platform reads every cited operator in one new run (at most
{MAX_EVIDENCE_ROWS} rows each) and refuses the report when a figure in a claim, the
summary or a caveat is not in that output: write figures as the output has them,
rounded, with a decimal point (12.3, not 12,3), and compute differences, shares
and counts in a transform or statistic first. Each call posts a new report."""


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def delegate_analysis(
        brief: str,
        title: str,
        session_id: SessionId,
        analysis: FromDishka[AnalysisService],
        operator_ids: Sequence[OperatorId] = (),
    ) -> Session:
        """Hand an analysis question about data the project already has to ADA's analyst:
        trends, gaps between regions or against the best, outliers, data quality, where a
        change comes from. `brief` states the question, `operator_ids` the operators to
        analyse (it can find others itself), `title` names it in a few words. The analyst
        works in a child session of this one with vetted statistics and transforms. This
        returns at once; its report comes back into this session later: findings, each
        with the operator that shows it, checked against one run. Build widgets from those
        operators to show them."""
        return await analysis.delegate(
            session_id, brief, title, tuple(operator_ids), calling_agent()
        )

    @mcp.tool(description=REPORT_FINDINGS)
    @inject
    async def report_findings(
        summary: str,
        findings: Sequence[Finding],
        session_id: SessionId,
        analysis: FromDishka[AnalysisService],
        caveats: Sequence[str] = (),
        not_shown: Sequence[str] = (),
    ) -> SessionEntry:
        return await analysis.report(
            session_id, summary, findings, caveats, not_shown, calling_agent()
        )
