"""Context.dev's parse API as an engine for document sources (`options.engine:
"context.dev"`).

The PDF is sent as raw bytes to POST /v1/parse, which answers at once with the document as
GitHub-flavoured Markdown, each page starting with an `<!-- page N -->` marker. The reader
makes the same rows of it as pdfplumber's: pages (`page, text`), or the rows of every
Markdown table (`page, table, row, cells`). A scan without a text layer is parsed again
with OCR. The key comes from CONTEXT_DEV_API_KEY and is sent nowhere else.
"""

import re

import httpx

from ada.adapters.web import error_code
from ada.core.models.errors import Invalid, Unavailable

BASE_URL = "https://api.context.dev/v1"
# Large PDFs take a while to parse; the API answers synchronously.
TIMEOUT = httpx.Timeout(180.0, connect=10.0)

_PAGE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)
_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


class ContextDevParser:
    def __init__(self, client: httpx.AsyncClient, api_key: str | None, base_url: str = BASE_URL):
        self.client = client
        self.api_key = api_key
        self.base_url = base_url

    async def markdown(self, content: bytes, origin: str) -> str:
        """The PDF as Markdown with page markers. Raises Invalid with the API's reason."""
        if not self.api_key:
            raise Invalid(
                "The Context.dev engine needs CONTEXT_DEV_API_KEY in the backend's "
                "environment (.env.local in development)"
            )
        answer = await self._parse(content, ocr=False)
        if answer.status_code == 400 and _code(answer) == "PDF_IMAGES_ONLY":
            # A scan: worth one more credit per page to read it at all.
            answer = await self._parse(content, ocr=True)
        if answer.status_code == 200:
            return str(answer.json().get("markdown") or "")
        reason = _reason(answer, self.api_key)
        match answer.status_code:
            case 401 | 403:
                raise Invalid(f"Context.dev refused the key: {reason}")
            case 402:
                raise Invalid(f"Context.dev has no credits left: {reason}")
            case 413:
                raise Invalid(f"{origin} is larger than Context.dev accepts (50 MiB)")
            case 429 | 503:
                raise Unavailable(f"Context.dev is busy: {reason}")
            case _:
                raise Invalid(f"Context.dev could not parse {origin}: {reason}")

    async def _parse(self, content: bytes, ocr: bool) -> httpx.Response:
        params = {"extension": "pdf", "includeNumberedPages": "true", "includeLinks": "false"}
        if ocr:
            params["ocr"] = "true"
        try:
            return await self.client.post(
                f"{self.base_url}/parse",
                params=params,
                content=content,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/pdf",
                },
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise Unavailable(f"Context.dev could not be reached: {error}") from error


def markdown_pages(markdown: str) -> list[tuple[int, str]]:
    """One row per page marker, with the page's Markdown; one page 1 without markers."""
    parts = _PAGE.split(markdown)
    if len(parts) == 1:
        return [(1, markdown.strip())]
    # split gives [before, number, text, number, text, ...]; text before page 1 is a preamble.
    return [(int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def markdown_tables(markdown: str) -> list[tuple[int, int, int, list[str]]]:
    """The rows of every Markdown table, per page: (page, table, row, cells), numbered from
    1 like pdfplumber's. The header is row 1; the separator line is no row."""
    rows: list[tuple[int, int, int, list[str]]] = []
    for page, text in markdown_pages(markdown):
        table = 0
        row = 0
        inside = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|"):
                if not inside:
                    inside = True
                    table += 1
                    row = 0
                if _SEPARATOR.match(stripped):
                    continue
                row += 1
                rows.append((page, table, row, _cells(stripped)))
            else:
                inside = False
    return rows


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    # A pipe inside a cell is escaped as \|.
    cells = re.split(r"(?<!\\)\|", body)
    return [cell.strip().replace("\\|", "|") for cell in cells]


def _code(answer: httpx.Response) -> str | None:
    try:
        body = answer.json()
    except ValueError:
        return None
    return body.get("error_code") or body.get("code") if isinstance(body, dict) else None


def _reason(answer: httpx.Response, key: str) -> str:
    """The status and the checked error code. Nothing else of the body is quoted: an
    authentication error may echo the key."""
    try:
        body = answer.json()
    except ValueError:
        body = None
    code = error_code(body, key) if isinstance(body, dict) else None
    return f"{code} (HTTP {answer.status_code})" if code else f"HTTP {answer.status_code}"
