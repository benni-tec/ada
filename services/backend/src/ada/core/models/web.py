"""The web on ADA's own accounts: search hits (Exa or Context.dev), Context.dev's pages,
crawls, answers and page monitors, and the refusal when a key or address is not set."""

import re
from enum import StrEnum
from typing import Any

from pydantic import SecretStr

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid


class SearchScope(StrEnum):
    """Which sites a web search looks at (the domain lists are in adapters/web/scopes.py)."""

    # Statistics offices, registries and open-data portals.
    DATA = "data"
    NEWS = "news"
    # Papers: PubMed and PubMed Central, preprint servers, journals.
    RESEARCH = "research"
    ANY = "any"


class SearchHit(DomainModel):
    url: str
    title: str
    # The publication date when the search engine knows it.
    published: str | None = None
    snippet: str = ""


class SearchResults(DomainModel):
    hits: list[SearchHit]
    # What Context.dev charged for the search; None for an engine that does not charge in
    # Context.dev's credits (Exa, counted at a fixed weight).
    credits: int | None = None


class PdfOptions(DomainModel):
    """Which pages of a PDF Context.dev reads (from 1, both ends inclusive; None from the
    first or to the last), and whether it reads them with OCR, for tables that are
    images. Each page starts with a `<!-- page N -->` line."""

    start: int | None = None
    end: int | None = None
    ocr: bool = False


def pdf_options(start: object, end: object, ocr: object) -> PdfOptions:
    """PdfOptions from untrusted values, or Invalid saying what is wrong with them."""
    for name, page in (("start", start), ("end", end)):
        if page is not None and (type(page) is not int or page < 1):
            raise Invalid(f"The {name} page of a PDF is a page number from 1")
    if isinstance(start, int) and isinstance(end, int) and end < start:
        raise Invalid("The end page of a PDF is not before its start page")
    if not isinstance(ocr, bool):
        raise Invalid("ocr is true or false")
    return PdfOptions(
        start=start if isinstance(start, int) else None,
        end=end if isinstance(end, int) else None,
        ocr=ocr,
    )


def pdf_page_range(pages: str) -> tuple[int, int]:
    """The first and last page of "25-26", or of "25" alone; Invalid otherwise."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", pages)
    if match is None:
        raise Invalid(
            f'pdf_pages is a page or a range of pages, e.g. "25" or "25-26", not {pages!r}'
        )
    start = int(match[1])
    end = int(match[2]) if match[2] else start
    pdf_options(start, end, False)
    return start, end


class WebPage(DomainModel):
    # The final address, after redirects.
    url: str
    title: str | None = None
    markdown: str
    # What Context.dev charged for reading it, when it said (not for the pages of a crawl,
    # which has its own count).
    credits: int | None = None


class WebLink(DomainModel):
    url: str
    title: str | None = None


class Crawl(DomainModel):
    pages: list[WebPage]
    # What Context.dev charged; one per page when it does not say.
    credits: int


class Answer(DomainModel):
    # In the shape of the json_format asked for.
    content: JsonObject
    # The URLs the answer read or cites.
    sources: list[str]
    credits: int


class Extraction(DomainModel):
    """Rows a model read out of a page, in the columns asked for (null where the page
    does not state a value)."""

    rows: list[dict[str, Any]]
    # Whether the page was longer than the extraction reads (Context.dev: 100,000
    # characters).
    truncated: bool = False
    credits: int


class Monitor(DomainModel):
    """A page monitor at Context.dev. The secret signs its webhook deliveries."""

    id: str
    secret: SecretStr


class WebNotConfigured(Invalid):
    """A web tool whose key or address is not set. The message names the setting."""

    def __init__(self, what: str, remedy: str) -> None:
        super().__init__(f"{what} is not configured: {remedy}")


def search_not_configured() -> WebNotConfigured:
    # Either engine searches: Exa when its key is set, else Context.dev.
    return WebNotConfigured("web search", "set EXA_API_KEY or CONTEXT_DEV_API_KEY")


def reading_not_configured() -> WebNotConfigured:
    return WebNotConfigured("page reading", "CONTEXT_DEV_API_KEY is not set")


def watching_not_configured() -> WebNotConfigured:
    return WebNotConfigured("watching", "ADA_PUBLIC_URL is not set")
