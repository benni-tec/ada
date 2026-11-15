from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ada.adapters.db.tables import AlertDeliveryRow
from ada.core.models.alerts import AlertDelivery
from ada.core.models.base import Id
from ada.core.models.events import Event, EventType
from ada.core.ports.events import EventBroadcaster


class SqlDeliveryRepository:
    """Each background delivery owns a short transaction, independent of the check."""

    def __init__(self, engine: AsyncEngine, events: EventBroadcaster) -> None:
        self.engine = engine
        self.events = events

    async def add(self, delivery: AlertDelivery) -> None:
        async with AsyncSession(self.engine) as session, session.begin():
            session.add(AlertDeliveryRow(**delivery.model_dump()))
        await self.events.publish(
            Event(
                type=EventType.ALERT_DELIVERED,
                project_id=delivery.project_id,
                payload={"rule_id": str(delivery.rule_id)},
                at=delivery.created_at,
            )
        )

    async def list(self, project_id: Id) -> list[AlertDelivery]:
        async with AsyncSession(self.engine) as session:
            result = await session.scalars(
                select(AlertDeliveryRow)
                .where(AlertDeliveryRow.project_id == project_id)
                .order_by(AlertDeliveryRow.created_at)
            )
            return [AlertDelivery.model_validate(row, from_attributes=True) for row in result]
