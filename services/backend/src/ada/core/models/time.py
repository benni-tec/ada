from datetime import date

from ada.core.models.base import DomainModel


class Interval(DomainModel):
    """A period of data: both ends inclusive. A year is 1 January to 31 December; a
    multi-year window such as 2022-2024 is one interval, not three."""

    start: date
    end: date


class TimeRange(DomainModel):
    """What a run or a dashboard asks for. An open end means no bound on that side."""

    start: date | None = None
    end: date | None = None
