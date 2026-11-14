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
            f"{method} {url} answered {response.status_code}{_body_code(response, token)}",
            response.status_code,
        )
    try:
        answer: dict[str, Any] = response.json()
    except ValueError:
        raise Unavailable(f"{method} {url} answered something other than JSON") from None
    if not isinstance(answer, dict):
        raise Unavailable(f"{method} {url} answered something other than a JSON object")
    return answer


def _body_code(response: httpx.Response, token: str) -> str:
    """ ": <code>" from the error code of an error answer, else nothing."""
    try:
        body = response.json()
    except ValueError:
        return ""
    code = error_code(body, token) if isinstance(body, dict) else None
    return f": {code}" if code else ""


def error_code(answer: dict[str, Any], token: str) -> str | None:
    """The short `error_code` field of a provider's answer, when it is one. Nothing else of
    an answer is ever quoted in an error: an authentication error may echo the key, and a
    page's own text is no message of ours."""
    code = answer.get("error_code")
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code) and token not in code:
        return code
    return None
