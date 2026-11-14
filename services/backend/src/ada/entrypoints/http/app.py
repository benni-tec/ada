from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka import Provider
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import APIRouter, FastAPI
from fastmcp.utilities.lifespan import combine_lifespans

from ada.composition import create_container
from ada.config import Settings
from ada.entrypoints.http import health
from ada.entrypoints.mcp.server import McpPathMiddleware, create_mcp


def create_app(settings: Settings | None = None, *providers: Provider) -> FastAPI:
    """The API, served under /api and /mcp. The gateway serves the frontend.

    providers override the composition root's, e.g. fakes in tests.
    """
    settings = settings or Settings()
    container = create_container(settings, FastapiProvider(), *providers)
    mcp_app = create_mcp(container).http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await container.close()

    app = FastAPI(
        title="ADA",
        # The MCP session manager must run alongside the app; it shuts down first.
        lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    api = APIRouter(prefix="/api")
    for module in (health,):
        api.include_router(module.router)
    app.include_router(api)
    app.mount("/mcp", mcp_app)
    app.add_middleware(McpPathMiddleware)
    setup_dishka(container, app)
    return app
