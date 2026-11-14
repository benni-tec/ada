from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.agents import AgentTurn, ModelList
from ada.core.models.base import Id
from ada.core.services.ports.agents import AgentTurnService

router = APIRouter(route_class=DishkaRoute, tags=["agent"])


@router.get("/llm/models")
async def list_models(service: FromDishka[AgentTurnService]) -> ModelList:
    """The configured models (see the settings routes), whether each can be used (a
    provider without the key it needs makes its models unavailable, with the reason), and
    the session agent. Keys are never returned."""
    return await service.models()


@router.get("/sessions/{session_id}/turns")
async def list_turns(session_id: Id, service: FromDishka[AgentTurnService]) -> Sequence[AgentTurn]:
    """The agent's turns in a session, oldest first."""
    return await service.turns(session_id)


@router.get("/turns/{turn_id}")
async def get_turn(turn_id: Id, service: FromDishka[AgentTurnService]) -> AgentTurn:
    """One turn with its parts so far. A client that connects late reads this, then applies
    the agent.turn_part events with a higher index."""
    return await service.get(turn_id)


@router.post("/turns/{turn_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_turn(turn_id: Id, service: FromDishka[AgentTurnService]) -> AgentTurn:
    """Ask a turn to stop: a queued one is cancelled at once, a running one stops at its
    next step and then reports agent.turn_finished. A finished turn is returned as it is."""
    return await service.cancel(turn_id)
