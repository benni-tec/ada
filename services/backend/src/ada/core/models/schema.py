from enum import StrEnum

from ada.core.models.base import DomainModel
from ada.core.models.time import Grain


class ColumnType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    JSON = "json"


class Column(DomainModel):
    name: str
    type: ColumnType
    nullable: bool = True


class TimeRole(DomainModel):
    """Which columns hold the period a row describes: its first and last day, both
    inclusive, as dates."""

    start: str
    end: str
    # What every period spans, e.g. a year; None for windows such as 2020-2024 or periods
    # of mixed length. Pushing a time range down to a source needs one.
    grain: Grain | None = None


class GeoRole(DomainModel):
    """Which column holds a region code, in which code system and at which level, e.g.
    system "sotkanet" and level "wellbeing_services_county". Level "mixed" says the column
    holds regions of several levels, as Sotkanet's answers do (ada.core.services.schema.geo
    lists the known systems and levels)."""

    code: str
    system: str
    level: str


class MeasureRole(DomainModel):
    """A value column and the columns that qualify it."""

    value: str
    # Bounds of its confidence interval.
    lower: str | None = None
    upper: str | None = None
    # Boolean column: the value was withheld, e.g. for small counts.
    suppressed: str | None = None
    # Share of cases the value is based on, 0 to 1.
    coverage: str | None = None


class Roles(DomainModel):
    time: TimeRole | None = None
    geo: GeoRole | None = None
    measures: tuple[MeasureRole, ...] = ()


class OutputKind(StrEnum):
    TABLE = "table"
    # Text with structure, e.g. a parsed PDF.
    DOCUMENT = "document"
    # A structured result that is not rows, e.g. a model fit or generated recommendations.
    RESULT = "result"


class Schema(DomainModel):
    """What an operator produces. Every operator states it; `derived` says whether the
    platform worked it out from the inputs or its creator declared it."""

    kind: OutputKind = OutputKind.TABLE
    columns: tuple[Column, ...] = ()
    roles: Roles = Roles()
    derived: bool = False

    def column(self, name: str) -> Column | None:
        return next((column for column in self.columns if column.name == name), None)
