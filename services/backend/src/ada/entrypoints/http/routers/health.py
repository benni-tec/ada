from typing import Literal

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from ada.core.models.health import Health
from ada.core.services.ports.system import SystemStatusService

router = APIRouter(route_class=DishkaRoute, tags=["health"])


class Liveness(BaseModel):
    status: Literal["ok"]


@router.get("/health")
async def health(service: FromDishka[SystemStatusService], response: Response) -> Health:
    result = await service.health()
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/health/live")
async def live() -> Liveness:
    """Liveness for container healthchecks: the API answers, whatever its dependencies do."""
    return Liveness(status="ok")
