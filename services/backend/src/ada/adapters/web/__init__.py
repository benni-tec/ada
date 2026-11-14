"""Web tools: Exa for search (exa.py) and Context.dev for page reading (context.py)."""

from typing import Any

import httpx

from ada.core.models.errors import Unavailable


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
        raise Unavailable(f"{method} {url} answered {response.status_code}: {response.text[:300]}")
    answer: dict[str, Any] = response.json()
    return answer
