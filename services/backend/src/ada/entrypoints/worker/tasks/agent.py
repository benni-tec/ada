import logging
from uuid import UUID

from dishka import AsyncContainer
from dishka.integrations.taskiq import FromDishka

from ada.core.services.ports.agents import AgentTurnService
from ada.entrypoints.mcp.agent import InProcessToolbox
from ada.entrypoints.worker.registry import task

logger = logging.getLogger(__name__)


@task()
async def run_turn(
    turn_id: str,
    *,
    service: FromDishka[AgentTurnService],
    container: FromDishka[AsyncContainer],
) -> None:
    """Queued when a message is posted and a session agent is configured. Runs the agent
    with the platform's own MCP tools, each call a unit of work of its own, so what it
    builds is stored and announced as it goes, like an external agent's work."""
    try:
        turn = UUID(turn_id)
        # The worker runs several tasks at once, in several processes: without this, two
        # turns of one session could run side by side, e.g. the turn a research report
        # queues while the turn that delegated is still running.
        await service.wait(turn)
        await service.run(turn, InProcessToolbox(container))
    except Exception:
        # The service ends every turn it started, failed or not; this is for what happens
        # before (the turn cannot be read). Ending normally keeps the worker running.
        logger.exception("Running agent turn %s failed", turn_id)
