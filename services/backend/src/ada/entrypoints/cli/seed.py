"""`ada seed-demo`: the health demo's project, with the public sources it reads."""

from dishka import AsyncContainer

from ada.adapters.sources.examples import EXAMPLES
from ada.core.models.base import Id
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService

DEMO_PROJECT = "Nordic cancer care"


async def seed_demo(container: AsyncContainer, refresh: bool = False) -> Id:
    """Create the demo project and register the example sources in it, unless a project of
    that name exists; then it is left as it is. Registering fetches nothing: `refresh`
    queues a forced refresh of every source in the project for the worker."""
    async with container() as request:
        projects = await request.get(ProjectService)
        sources = await request.get(SourceService)
        existing = [p for p in await projects.list() if p.name == DEMO_PROJECT]
        if existing:
            project = existing[0]
            print(f"Project {DEMO_PROJECT!r} exists: {project.id}")
        else:
            project = await projects.create(DEMO_PROJECT)
            for example in EXAMPLES:
                await sources.register(project.id, **example.registration())
            print(f"Created project {DEMO_PROJECT!r}: {project.id}")
        registered = await sources.list(project.id)
        for source in registered:
            print(f"  source {source.id}  {source.name}")

    if refresh:
        # Queued after the registrations above have committed, so the worker finds them.
        dispatcher = await container.get(TaskDispatcher)
        for source in registered:
            await dispatcher.refresh_source(source.id, force=True)
        print(f"Queued a refresh of {len(registered)} sources; the worker fetches them.")
    return project.id
