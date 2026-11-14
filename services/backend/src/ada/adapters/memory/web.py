from datetime import date

from ada.core.models.base import Id
from ada.core.ports.web import WebBudget


class MemoryWebBudget(WebBudget):
    """The credits per project and day in a dict; memory has no transactions to outlive."""

    def __init__(self) -> None:
        self.spent: dict[tuple[Id, date], int] = {}

    async def spend(self, project_id: Id, day: date, credits: int, limit: int) -> bool:
        spent = self.spent.get((project_id, day), 0)
        if spent + credits > limit:
            return False
        self.spent[(project_id, day)] = spent + credits
        return True

    async def adjust(self, project_id: Id, day: date, credits: int) -> None:
        key = (project_id, day)
        self.spent[key] = max(self.spent.get(key, 0) + credits, 0)
