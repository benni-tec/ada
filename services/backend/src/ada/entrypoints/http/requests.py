from pydantic import ConfigDict

from ada.core.models.base import DomainModel, Id


class Request(DomainModel):
    """Base of request bodies. A field the route does not know is an error, not ignored:
    a client that sends data to a widget, or misspells `expected_revision`, must find out."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Order(Request):
    """A new order of a project's dashboards or reports: every id of them, once."""

    ids: list[Id]
