"""What the web tools return: search hits, page text and page monitors."""

from enum import StrEnum

from pydantic import SecretStr

from ada.core.models.base import DomainModel
from ada.core.models.errors import Invalid


class SearchScope(StrEnum):
    DATA = "data"
    NEWS = "news"
    RESEARCH = "research"
    ANY = "any"


class SearchHit(DomainModel):
    url: str
    title: str
    published: str | None = None
    snippet: str = ""


class PageText(DomainModel):
    url: str
    title: str | None = None
    text: str


class Monitor(DomainModel):
    """A page monitor at the provider. The secret signs its webhook deliveries."""

    id: str
    secret: SecretStr


class WebNotConfigured(Invalid):
    """A web tool whose key or address is not set. The message names the setting."""

    def __init__(self, what: str, setting: str) -> None:
        super().__init__(f"{what} is not configured: {setting} is not set")


def search_not_configured() -> WebNotConfigured:
    return WebNotConfigured("web search", "EXA_API_KEY")


def reading_not_configured() -> WebNotConfigured:
    return WebNotConfigured("page reading", "CONTEXT_API_KEY")


def watching_not_configured() -> WebNotConfigured:
    return WebNotConfigured("watching", "ADA_PUBLIC_URL")
