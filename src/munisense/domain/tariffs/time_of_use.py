"""Time of use: period names and the cited calendar of a tariff version (ADR-0016).

Times are minutes after midnight in South African Standard Time (UTC+02:00, no daylight
saving). A day's schedule is a list of `[start, end)` ranges that cover the 1,440 minutes
of the day exactly once, each naming a period. The calendar has one schedule for each
season and day type. Public holidays come in P4-6; until then a date's day type is its
day of the week.
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from munisense.domain.base import DomainError, DomainModel
from munisense.domain.citations import Cited
from munisense.domain.tariffs.components import (
    ComponentName,
    PrintedLabel,
    SeasonDates,
    check_covers_the_year_once,
)

MINUTES_IN_A_DAY = 24 * 60


class TouPeriod(StrEnum):
    """A time-of-use period, as a calendar names its time ranges (ADR-0016 point 1)."""

    PEAK = "peak"
    STANDARD = "standard"
    OFF_PEAK = "off_peak"


class DayType(StrEnum):
    """How a tariff treats a day: weekdays, Saturdays and Sundays have their own hours."""

    WEEKDAY = "weekday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class UndefinedPeriodError(DomainError):
    """A period was named that the version's calendar does not define."""


class TimeRange(DomainModel):
    """Minutes `[start_minute, end_minute)` of a day, in one period."""

    start_minute: Annotated[int, Field(ge=0, le=MINUTES_IN_A_DAY - 1)]
    end_minute: Annotated[int, Field(ge=1, le=MINUTES_IN_A_DAY)]
    period: TouPeriod

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.start_minute >= self.end_minute:
            msg = "a time range must end after it starts"
            raise ValueError(msg)
        return self


class DaySchedule(DomainModel):
    """The periods of one day type in one season, in time order, covering the whole day.
    Each range is cited (ADR-0006): the source may draw them rather than print them
    (ADR-0016 point 5)."""

    season: ComponentName
    day_type: DayType
    ranges: Annotated[tuple[Cited[TimeRange], ...], Field(min_length=1, max_length=48)]

    @model_validator(mode="after")
    def _covers_the_day_once(self) -> Self:
        expected_start = 0
        for cited in self.ranges:
            if cited.value.start_minute != expected_start:
                problem = "a gap" if cited.value.start_minute > expected_start else "an overlap"
                msg = (
                    f"the {self.season} {self.day_type} ranges must cover the day once, "
                    f"in order; there is {problem} at minute {expected_start}"
                )
                raise ValueError(msg)
            expected_start = cited.value.end_minute
        if expected_start != MINUTES_IN_A_DAY:
            msg = f"the {self.season} {self.day_type} ranges must run to midnight"
            raise ValueError(msg)
        return self

    def period_at(self, minute: int) -> TouPeriod:
        """The period at a minute of the day (0 to 1,439)."""
        if not 0 <= minute < MINUTES_IN_A_DAY:
            msg = f"minute {minute} is not in a day"
            raise ValueError(msg)
        for cited in self.ranges:
            if minute < cited.value.end_minute:
                return cited.value.period
        raise AssertionError  # pragma: no cover - the validator covers the whole day


class CalendarSeason(DomainModel):
    """A season of the calendar: its name, printed label and cited dates."""

    name: ComponentName
    label: Cited[PrintedLabel]
    dates: Cited[SeasonDates]


class TouCalendar(DomainModel):
    """One cited time-of-use calendar for a tariff version (ADR-0016 point 1).

    Its seasons cover every day of the year once; it has exactly one day schedule for each
    season and day type, and each schedule covers the day once.
    """

    seasons: Annotated[tuple[CalendarSeason, ...], Field(min_length=1, max_length=12)]
    schedules: Annotated[tuple[DaySchedule, ...], Field(min_length=3, max_length=36)]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        names = [season.name for season in self.seasons]
        if len(set(names)) != len(names):
            msg = "season names must be unique within a calendar"
            raise ValueError(msg)
        check_covers_the_year_once([season.dates.value for season in self.seasons])
        keys = [(schedule.season, schedule.day_type) for schedule in self.schedules]
        if len(set(keys)) != len(keys):
            msg = "a calendar has one schedule for each season and day type"
            raise ValueError(msg)
        for season, _ in keys:
            if season not in names:
                msg = f"a schedule names the season {season!r}, which the calendar lacks"
                raise ValueError(msg)
        for name in names:
            for day_type in DayType:
                if (name, day_type) not in keys:
                    msg = f"the calendar has no {day_type} schedule for the season {name!r}"
                    raise ValueError(msg)
        return self

    @property
    def periods(self) -> frozenset[TouPeriod]:
        """Every period some schedule uses."""
        return frozenset(r.value.period for s in self.schedules for r in s.ranges)

    def require_defined(self, periods: Iterable[TouPeriod]) -> None:
        """Refuse any period the calendar does not define (used when pricing, P4-7)."""
        missing = sorted(set(periods) - self.periods)
        if missing:
            msg = f"the calendar does not define the period(s) {', '.join(missing)}"
            raise UndefinedPeriodError(msg)

    def season_for(self, day: date) -> CalendarSeason:
        """The season containing the day (the validators guarantee exactly one)."""
        found = next((s for s in self.seasons if s.dates.value.contains(day)), None)
        if found is None:  # pragma: no cover - only reachable if validation was skipped
            msg = f"no season contains {day}"
            raise AssertionError(msg)
        return found

    def day_type(self, day: date) -> DayType:
        """The day's type by its day of the week (public holidays: P4-6)."""
        weekday = day.weekday()
        if weekday == 5:
            return DayType.SATURDAY
        if weekday == 6:
            return DayType.SUNDAY
        return DayType.WEEKDAY

    def schedule_for(self, day: date) -> DaySchedule:
        """The day's schedule: its season's, for its day type (the validators guarantee
        exactly one)."""
        season, day_type = self.season_for(day).name, self.day_type(day)
        key = (season, day_type)
        found = next((s for s in self.schedules if (s.season, s.day_type) == key), None)
        if found is None:  # pragma: no cover - only reachable if validation was skipped
            msg = f"no {day_type} schedule for the season {season!r}"
            raise AssertionError(msg)
        return found

    def period_for(self, day: date, minute: int) -> TouPeriod:
        """The period at a minute (0 to 1,439, SAST) of a day."""
        return self.schedule_for(day).period_at(minute)
