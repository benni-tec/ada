from collections.abc import Sequence
from typing import Protocol

from ada.core.models.base import JsonObject
from ada.core.models.web import Monitor, PageText, SearchHit, SearchScope


class WebSearch(Protocol):
    async def search(self, query: str, scope: SearchScope, limit: int) -> Sequence[SearchHit]: ...

    async def contents(self, urls: Sequence[str]) -> Sequence[PageText]:
        """The text of each page that could be fetched; a page that failed is left out."""
        ...


class PageReader(Protocol):
    async def read(self, url: str) -> PageText: ...

    async def extract(self, url: str, instruction: str, columns: Sequence[str]) -> list[JsonObject]:
        """Rows with the given columns, as the page states them (null where it does not)."""
        ...

    async def watch(self, url: str, webhook_url: str) -> Monitor:
        """Watch the page; the webhook is called when it changes."""
        ...

    async def unwatch(self, monitor_id: str) -> None: ...
