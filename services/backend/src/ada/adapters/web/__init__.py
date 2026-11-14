"""Web tools: Exa for search (exa.py) and Context.dev for page reading (context.py)."""

import re
from typing import Any

import httpx

from ada.core.models.errors import Unavailable


class ProviderAnswered(Unavailable):
    """The provider answered with an error status."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


async def send_json(
    client: httpx.AsyncClient, method: str, url: str, token: str, body: dict[str, Any] | None
) -> dict[str, Any]:
    """One JSON request with a bearer key. Raises Unavailable when it fails or the answer
    is an error; the message never contains the key."""
    try:
        response = await client.request(
            method, url, json=body, headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.HTTPError as error:
        raise Unavailable(f"{method} {url} failed: {str(error) or type(error).__name__}") from error
    if response.is_error:
        raise ProviderAnswered(
            f"{method} {url} answered {response.status_code}{_error_code(response, token)}",
            response.status_code,
        )
    try:
        answer: dict[str, Any] = response.json()
    except ValueError:
        raise Unavailable(f"{method} {url} answered something other than JSON") from None
    if not isinstance(answer, dict):
        raise Unavailable(f"{method} {url} answered something other than a JSON object")
    return answer


def _error_code(response: httpx.Response, token: str) -> str:
    """ ": <code>" from the short error code field of an error answer, else nothing. The raw
    body is never quoted: an authentication error may echo the key."""
    try:
        body = response.json()
    except ValueError:
        return ""
    code = body.get("error_code") if isinstance(body, dict) else None
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code) and token not in code:
        return f": {code}"
    return ""
