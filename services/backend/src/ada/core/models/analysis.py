from datetime import datetime

from ada.core.models.base import DomainModel
from ada.core.models.schema import Column, Schema
from ada.core.models.sources import DataFormat


class FetchedData(DomainModel):
    """What a source reader returns: the bytes as they came, before anything reads them."""

    content: bytes
    format: DataFormat
    fetched_at: datetime
    # Where exactly it came from, e.g. the final URL with its query.
    origin: str


class StoredSnapshot(DomainModel):
    """What the analysis store reports after writing a snapshot."""

    location: str
    content_hash: str
    row_count: int
    output: Schema


class Query(DomainModel):
    """SQL over snapshots. `relations` maps each table name the SQL uses to a snapshot
    location; a chain of pass-through operators is fused into one such query."""

    sql: str
    relations: dict[str, str] = {}


class Rows(DomainModel):
    """A small result held in memory: a preview or a widget's data. Never whole snapshots."""

    columns: tuple[Column, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool = False
