from typing import Literal

from pydantic import Field

from ada.core.models.base import DomainModel

Part = Literal["ok", "unavailable"]


class Health(DomainModel):
    status: Literal["ok", "degraded"] = Field(description="Aggregate: ok only if every part is ok")
    api: Literal["ok"] = Field(description="Always ok when the API can answer at all")
    database: Part = Field(description="PostgreSQL, which holds the definitions")
    queue: Part = Field(description="Valkey, the task queue broker")
    worker: Part = Field(description="Task worker and scheduler, judged by their heartbeat")
    analysis_store: Part = Field(description="DuckDB over the snapshot directory")
    web_search: bool = Field(description="Web search is configured (EXA_API_KEY is set)")
    page_reading: bool = Field(
        description="Page reading is configured (CONTEXT_DEV_API_KEY is set)"
    )
    watching: bool = Field(
        description="Page watching is configured (CONTEXT_DEV_API_KEY and ADA_PUBLIC_URL are set)"
    )


class WebConfigured(DomainModel):
    """Which web features have the keys or address they need."""

    search: bool
    reading: bool
    watching: bool
