"""Time of use: period names and the cited calendar of a tariff version (ADR-0016).

Times are minutes after midnight in South African Standard Time (UTC+02:00, no daylight
saving). A day's schedule is a list of `[start, end)` ranges that cover the 1,440 minutes
of the day exactly once, each naming a period. The calendar has one schedule for each
season and day type. Public holidays are treated as the calendar's cited holiday rule
says (P4-6): either as the day of the week they fall on, or as listed by the tariff's own
document, which covers a stated window of dates; outside that window a day is refused,
because nothing can tell whether it is a holiday.
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Self, assert_never

from pydantic import Field, model_validator

from munisense.domain.base import DomainError, DomainModel
from munisense.domain.citations import Cited
from munisense.domain.periods import DateRange
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


class HolidayCoverageError(DomainError):
    """A day falls outside the dates the calendar's holiday list covers, so whether it is
    a holiday (and how it is treated) is unknown."""


class HolidayRule(StrEnum):
    """How public holidays are treated."""

    AS_DAY_OF_WEEK = "as_day_of_week"
    """Every holiday is treated as the day of the week it falls on (Eskom's Homeflex)."""
    LISTED = "listed"
    """The tariff's document lists the holidays of a stated window and how each is
    treated (Eskom's Appendix D for Megaflex and others)."""


class UnlistedHolidays(StrEnum):
    """How a list treats a holiday it does not name (for example one announced later)."""

    AS_DAY_OF_WEEK = "as_day_of_week"


class ListedHoliday(DomainModel):
    """One listed holiday and the day type it is treated as."""

    day: date
    treated_as: DayType

    @model_validator(mode="after")
    def _weekend_treatment(self) -> Self:
        if self.treated_as == DayType.WEEKDAY:
            msg = "a listed holiday is treated as a Saturday or a Sunday"
            raise ValueError(msg)
        return self


class HolidayTreatment(DomainModel):
    """The calendar's cited holiday rule (ADR-0016 point 1).

    `as_day_of_week` has no list. `listed` has a cited coverage window, at least one cited
    holiday inside it (in date order, each date once), and a cited rule for holidays it
    does not name. The coverage is a half-open `DateRange`: its `end` is the first day NOT
    covered (a list printed "to 30 June 2027" ends on 1 July 2027), unlike `SeasonDates`,
    whose end is inclusive as schedules print it. The only unlisted rule is "as the day of
    the week", the only one the engine can apply without a national holiday calendar.
    """

    rule: Cited[HolidayRule]
    coverage: Cited[DateRange] | None = None
    listed: Annotated[tuple[Cited[ListedHoliday], ...], Field(max_length=100)] = ()
    unlisted: Cited[UnlistedHolidays] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.rule.value == HolidayRule.AS_DAY_OF_WEEK:
            if self.coverage is not None or self.listed or self.unlisted is not None:
                msg = "holidays treated as the day of the week have no list or coverage"
                raise ValueError(msg)
            return self
        if self.coverage is None or not self.listed or self.unlisted is None:
            msg = "a holiday list needs its coverage, at least one holiday and an unlisted rule"
            raise ValueError(msg)
        days = [cited.value.day for cited in self.listed]
        if any(later <= earlier for earlier, later in pairwise(days)):
            msg = "listed holidays are in date order, each date once"
            raise ValueError(msg)
        outside = [d for d in days if not self.coverage.value.contains(d)]
        if outside:
            msg = f"a listed holiday is outside the list's coverage: {min(outside)}"
            raise ValueError(msg)
        return self

    def day_type(self, day: date) -> DayType:
        """The day's type: a listed holiday's treatment, otherwise its day of the week."""
        if self.rule.value == HolidayRule.LISTED:
            coverage = self.coverage.value if self.coverage is not None else None
            if coverage is None or not coverage.contains(day):
                # Fixed text: the day may come from a consumer's readings (ADR-0016 point 4).
                msg = "a day is outside the dates the holiday list covers"
                raise HolidayCoverageError(msg)
            for cited in self.listed:
                if cited.value.day == day:
                    return cited.value.treated_as
            unlisted = self.unlisted.value if self.unlisted is not None else None
            match unlisted:
                case UnlistedHolidays.AS_DAY_OF_WEEK:
                    return _day_of_week(day)
                case None:  # pragma: no cover - the validator requires the rule
                    raise AssertionError
                case _:  # pragma: no cover - every member is handled above
                    assert_never(unlisted)
        return _day_of_week(day)


def _day_of_week(day: date) -> DayType:
    weekday = day.weekday()  # Monday is 0
    if weekday == 5:
        return DayType.SATURDAY
    if weekday == 6:
        return DayType.SUNDAY
    return DayType.WEEKDAY


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
    holidays: HolidayTreatment

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
        """The day's type under the holiday rule (`HolidayCoverageError` outside a list's
        coverage)."""
        return self.holidays.day_type(day)

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
