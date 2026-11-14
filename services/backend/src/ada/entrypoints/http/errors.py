from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ada.core.models.errors import Conflict, Invalid, NotFound


def install(app: FastAPI) -> None:
    """Map the core's errors to responses. Every error body is {"detail": "..."}; a
    conflict adds the two revisions, so the client knows to read again."""

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, error: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status.HTTP_404_NOT_FOUND)

    @app.exception_handler(Conflict)
    async def _conflict(request: Request, error: Conflict) -> JSONResponse:
        return JSONResponse(
            {"detail": str(error), "expected_revision": error.expected, "revision": error.actual},
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(Invalid)
    async def _invalid(request: Request, error: Invalid) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status.HTTP_422_UNPROCESSABLE_CONTENT)
