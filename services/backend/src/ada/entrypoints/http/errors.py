from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ada.core.models.errors import Conflict, Invalid, NotConfigured, NotFound, Unavailable

DOMAIN_ERRORS = (NotFound, Conflict, Invalid, Unavailable, NotConfigured)


def response_for(error: Exception) -> JSONResponse:
    """The response for one of the core's errors. Every error body is {"detail": "..."}; a
    conflict adds the two revisions, so the client knows to read again."""
    match error:
        case NotFound():
            return JSONResponse({"detail": str(error)}, status.HTTP_404_NOT_FOUND)
        case Conflict():
            return JSONResponse(
                {
                    "detail": str(error),
                    "expected_revision": error.expected,
                    "revision": error.actual,
                },
                status.HTTP_409_CONFLICT,
            )
        case NotConfigured():
            # The platform's setup is in the way, not the request: no revisions to compare.
            return JSONResponse({"detail": str(error)}, status.HTTP_409_CONFLICT)
        case Unavailable():
            # Nothing is wrong with the request; the client may retry it later.
            return JSONResponse({"detail": str(error)}, status.HTTP_503_SERVICE_UNAVAILABLE)
        case _:
            return JSONResponse({"detail": str(error)}, status.HTTP_422_UNPROCESSABLE_CONTENT)


class DomainErrorMiddleware:
    """Turns the core's errors into responses, outside the request's container.

    FastAPI's exception handlers would answer from inside the app, so the request scope
    around it would end normally and commit what the request had written before failing,
    and broadcast its events. Answering out here lets the error pass through the scope
    first, which rolls the transaction back and drops the events.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watch(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watch)
        except DOMAIN_ERRORS as error:
            if started:
                # A streamed response failed midway; there is no status left to change.
                raise
            await response_for(error)(scope, receive, send)


def install(app: FastAPI) -> None:
    """Call after setup_dishka: the middleware added last is the outermost, and this one
    must sit outside the container's."""
    app.add_middleware(DomainErrorMiddleware)
