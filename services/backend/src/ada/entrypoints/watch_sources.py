"""Batch orchestration shared by HTTP and MCP; each page commits independently."""

import asyncio
from typing import Annotated
from uuid import uuid5

from dishka import AsyncContainer, Scope
from pydantic import ConfigDict, Field

from ada.core.models.base import DomainModel, Id
from ada.core.models.errors import Invalid, NotConfigured, Unavailable
from ada.core.models.sources import AccessKind, CheckEvery, DataFormat, Provenance
from ada.core.ports.sources import SourceLocks
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService

PAGE_TIMEOUT_SECONDS = 10


class WatchPage(DomainModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    name: str
    check_every: CheckEvery | None = None
    provenance: Provenance | None = None


type WatchPages = Annotated[list[WatchPage], Field(min_length=1, max_length=50)]


class WatchResult(DomainModel):
    url: str
    ok: bool
    source_id: Id | None = None
    error: str | None = None
    already_watched: bool = False


async def watch_pages(
    container: AsyncContainer, project_id: Id, pages: WatchPages
) -> list[WatchResult]:
    # Start at APP: sibling REQUEST scopes must not share an AsyncSession. Failures
    # leave their scope before being caught, so their transaction is rolled back.
    while container.scope is not Scope.APP:
        assert container.parent_container is not None
        container = container.parent_container
    async with asyncio.timeout(PAGE_TIMEOUT_SECONDS), container() as scope:
        await (await scope.get(ProjectService)).get(project_id)
    semaphore = asyncio.Semaphore(4)

    async def one(page: WatchPage) -> WatchResult:
        async with semaphore:
            try:
                async with asyncio.timeout(PAGE_TIMEOUT_SECONDS):
                    async with container() as scope:
                        # Also serialize this URL across simultaneous batch requests.
                        await (await scope.get(SourceLocks)).hold(
                            uuid5(project_id, page.url.strip())
                        )
                        service = await scope.get(SourceService)
                        existing = await service.list(project_id)
                        source = next((s for s in existing if s.address == page.url.strip()), None)
                        already = source is not None and source.monitor_id is not None
                        if source is None:
                            source = await service.register(
                                project_id,
                                page.name,
                                AccessKind.WEB,
                                page.url,
                                DataFormat.HTML,
                                provenance=page.provenance,
                            )
                        if not already:
                            source = await service.watch(source.id, page.check_every)
                    return WatchResult(
                        url=page.url, ok=True, source_id=source.id, already_watched=already
                    )
            except TimeoutError:
                return WatchResult(url=page.url, ok=False, error="Page watch timed out")
            except (Invalid, NotConfigured, Unavailable) as error:
                if isinstance(error, NotConfigured):
                    reason = "Watching needs CONTEXT_DEV_API_KEY, ADA_PUBLIC_URL and ADA_SECRET_KEY"
                elif isinstance(error, Unavailable):
                    reason = "Monitor service unavailable; retry this page"
                else:
                    reason = "Invalid page registration or monitor request"
                return WatchResult(url=page.url, ok=False, error=reason)
            except Exception:
                # Neither provider responses nor database errors (which may contain
                # credentials or SQL parameters) belong in a batch response.
                return WatchResult(url=page.url, ok=False, error="Could not register or watch page")

    # Share work for repeated URLs within this call, keeping input order in the result.
    tasks: dict[str, asyncio.Task[WatchResult]] = {}
    for page in pages:
        if page.url.strip() not in tasks:
            tasks[page.url.strip()] = asyncio.create_task(one(page))
    try:
        results = await asyncio.gather(*(tasks[page.url.strip()] for page in pages))
        seen: set[str] = set()
        ordered = []
        for page, result in zip(pages, results, strict=True):
            url = page.url.strip()
            ordered.append(
                result.model_copy(
                    update={
                        "url": page.url,
                        "already_watched": result.ok and (result.already_watched or url in seen),
                    }
                )
            )
            seen.add(url)
        return ordered
    finally:
        for task in tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
