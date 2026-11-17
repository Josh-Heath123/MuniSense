"""A half-open range of calendar dates, [start, end). Dates are passed in; no clock."""

from datetime import date
from typing import Self

from pydantic import model_validator

from munisense.domain.base import DomainModel


class DateRange(DomainModel):
    """The dates from `start` up to, but not including, `end`. Never empty."""

    start: date
    end: date

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.end <= self.start:
            msg = "a date range must end after it starts"
            raise ValueError(msg)
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end

    def covers(self, other: "DateRange") -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: "DateRange") -> bool:
        return self.start < other.end and other.start < self.end

    @property
    def is_whole_calendar_month(self) -> bool:
        """True when the range is exactly one calendar month (the 1st to the next 1st)."""
        if self.start.day != 1 or self.end.day != 1:
            return False
        if self.start.month == 12:
            return self.end == date(self.start.year + 1, 1, 1)
        return self.end == date(self.start.year, self.start.month + 1, 1)
