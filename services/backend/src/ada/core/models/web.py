"""The web on ADA's own accounts: Exa's search hits, Context.dev's pages, crawls, answers
and page monitors, and the refusal when a key or address is not set."""

from enum import StrEnum
from typing import Any

from pydantic import SecretStr

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid


class SearchScope(StrEnum):
    """Which sites a web search looks at (the domain lists are in adapters/web/exa.py)."""

    # Statistics offices, registries and open-data portals.
    DATA = "data"
    NEWS = "news"
    # Papers: PubMed, preprint servers, journals.
    RESEARCH = "research"
    ANY = "any"


class SearchHit(DomainModel):
    url: str
    title: str
    # The publication date when the search engine knows it.
    published: str | None = None
    snippet: str = ""


class WebPage(DomainModel):
    # The final address, after redirects.
    url: str
    title: str | None = None
    markdown: str


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

    def __init__(self, what: str, setting: str) -> None:
        super().__init__(f"{what} is not configured: {setting} is not set")


def search_not_configured() -> WebNotConfigured:
    return WebNotConfigured("web search", "EXA_API_KEY")


def reading_not_configured() -> WebNotConfigured:
    return WebNotConfigured("page reading", "CONTEXT_DEV_API_KEY")


def watching_not_configured() -> WebNotConfigured:
    return WebNotConfigured("watching", "ADA_PUBLIC_URL")
