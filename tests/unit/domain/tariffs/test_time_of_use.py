"""The time-of-use calendar (P4-5, ADR-0016 point 1). Hours here are fixtures."""

from datetime import date

import pytest
from pydantic import ValidationError

from munisense.domain.citations import Cited
from munisense.domain.tariffs import (
    DaySchedule,
    DayType,
    TimeRange,
    TouCalendar,
    TouPeriod,
    UndefinedPeriodError,
)
from support.builders import (
    FIXTURE_HOURS,
    FIXTURE_STATUS,
    fixture_calendar,
    fixture_citation,
    fixture_day,
)

CALENDAR = fixture_calendar()


def test_a_date_and_minute_give_the_season_day_type_and_period() -> None:
    wednesday_in_july = date(2026, 7, 15)
    assert CALENDAR.season_for(wednesday_in_july).name == "high"
    assert CALENDAR.day_type(wednesday_in_july) == DayType.WEEKDAY
    assert CALENDAR.period_for(wednesday_in_july, 18 * 60) == TouPeriod.PEAK  # 18:00
    assert CALENDAR.period_for(wednesday_in_july, 18 * 60 - 1) == TouPeriod.STANDARD  # 17:59
    assert CALENDAR.period_for(wednesday_in_july, 0) == TouPeriod.OFF_PEAK
    assert CALENDAR.period_for(wednesday_in_july, 1439) == TouPeriod.OFF_PEAK


def test_each_season_has_its_own_hours() -> None:
    """The same day type and minute in July (high season) and in January (low season)
    fall in different periods, so a lookup that ignored the season would be caught."""
    july, january = date(2026, 7, 15), date(2027, 1, 13)  # both Wednesdays
    assert CALENDAR.day_type(july) == CALENDAR.day_type(january) == DayType.WEEKDAY
    assert CALENDAR.period_for(july, 8 * 60) == TouPeriod.STANDARD
    assert CALENDAR.period_for(january, 8 * 60) == TouPeriod.PEAK
    assert CALENDAR.period_for(date(2026, 7, 19), 18 * 60) == TouPeriod.OFF_PEAK  # Sunday
    assert CALENDAR.period_for(date(2027, 1, 17), 18 * 60) == TouPeriod.STANDARD


def test_saturdays_and_sundays_have_their_own_schedules() -> None:
    assert CALENDAR.day_type(date(2026, 7, 18)) == DayType.SATURDAY
    assert CALENDAR.day_type(date(2026, 7, 19)) == DayType.SUNDAY
    assert CALENDAR.period_for(date(2026, 7, 18), 8 * 60) == TouPeriod.STANDARD
    assert CALENDAR.period_for(date(2026, 7, 19), 8 * 60) == TouPeriod.OFF_PEAK


def test_seasons_follow_their_dates_across_the_new_year() -> None:
    assert CALENDAR.season_for(date(2026, 8, 31)).name == "high"
    assert CALENDAR.season_for(date(2026, 9, 1)).name == "low"
    assert CALENDAR.season_for(date(2027, 1, 1)).name == "low"
    assert CALENDAR.season_for(date(2028, 2, 29)).name == "low"


@pytest.mark.parametrize("minute", [-1, 1440])
def test_a_minute_outside_the_day_is_refused(minute: int) -> None:
    with pytest.raises(ValueError, match="not in a day"):
        CALENDAR.period_for(date(2026, 7, 15), minute)


def test_the_calendar_lists_its_periods_and_refuses_others() -> None:
    assert CALENDAR.periods == frozenset(TouPeriod)
    CALENDAR.require_defined([TouPeriod.PEAK, TouPeriod.OFF_PEAK])
    no_standard: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(
        DayType, ((24 * 60, TouPeriod.OFF_PEAK),)
    ) | {DayType.WEEKDAY: ((18 * 60, TouPeriod.OFF_PEAK), (24 * 60, TouPeriod.PEAK))}
    two_periods = fixture_calendar(no_standard, no_standard)
    with pytest.raises(UndefinedPeriodError, match="standard"):
        two_periods.require_defined([TouPeriod.STANDARD])


def _range(start: int, end: int, period: TouPeriod = TouPeriod.OFF_PEAK) -> Cited[TimeRange]:
    return Cited[TimeRange](
        value=TimeRange(start_minute=start, end_minute=end, period=period),
        citation=fixture_citation(),
        status=FIXTURE_STATUS,
    )


@pytest.mark.parametrize(
    ("ranges", "problem"),
    [
        ((_range(0, 600), _range(660, 1440)), "a gap at minute 600"),
        ((_range(0, 600), _range(540, 1440)), "an overlap at minute 600"),
        ((_range(60, 1440),), "a gap at minute 0"),
        ((_range(0, 1380),), "run to midnight"),
        ((_range(600, 1440), _range(0, 600)), "a gap at minute 0"),  # out of order
    ],
)
def test_a_day_that_is_not_covered_exactly_once_is_refused(
    ranges: tuple[Cited[TimeRange], ...], problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        DaySchedule(season="high", day_type=DayType.WEEKDAY, ranges=ranges)


@pytest.mark.parametrize(("start", "end"), [(600, 600), (700, 600), (-1, 60), (0, 1441)])
def test_an_empty_or_impossible_range_is_refused(start: int, end: int) -> None:
    with pytest.raises(ValidationError):
        TimeRange(start_minute=start, end_minute=end, period=TouPeriod.PEAK)


def _without(calendar: TouCalendar, season: str, day_type: DayType) -> tuple[DaySchedule, ...]:
    return tuple(s for s in calendar.schedules if (s.season, s.day_type) != (season, day_type))


def test_a_missing_schedule_is_refused() -> None:
    with pytest.raises(ValidationError, match="no saturday schedule for the season 'low'"):
        TouCalendar(seasons=CALENDAR.seasons, schedules=_without(CALENDAR, "low", DayType.SATURDAY))


def test_a_second_schedule_for_one_season_and_day_type_is_refused() -> None:
    with pytest.raises(ValidationError, match="one schedule for each season and day type"):
        TouCalendar(
            seasons=CALENDAR.seasons, schedules=(*CALENDAR.schedules, CALENDAR.schedules[0])
        )


def test_a_schedule_for_an_unknown_season_is_refused() -> None:
    extra = fixture_day("summer", DayType.SUNDAY, FIXTURE_HOURS[DayType.SUNDAY])
    with pytest.raises(ValidationError, match="names the season 'summer'"):
        TouCalendar(seasons=CALENDAR.seasons, schedules=(*CALENDAR.schedules, extra))


def test_seasons_that_do_not_cover_the_year_once_are_refused() -> None:
    with pytest.raises(ValidationError, match="cover every day once; 01 January has no season"):
        TouCalendar(
            seasons=CALENDAR.seasons[:1],
            schedules=tuple(s for s in CALENDAR.schedules if s.season == "high"),
        )
    with pytest.raises(ValidationError, match="unique within a calendar"):
        TouCalendar(
            seasons=(CALENDAR.seasons[0], CALENDAR.seasons[0]), schedules=CALENDAR.schedules
        )


def test_a_day_has_at_most_48_ranges() -> None:
    def day(count: int) -> tuple[Cited[TimeRange], ...]:
        return tuple(_range(i * 30, (i + 1) * 30 if i < count - 1 else 1440) for i in range(count))

    assert len(DaySchedule(season="high", day_type=DayType.SUNDAY, ranges=day(48)).ranges) == 48
    with pytest.raises(ValidationError):
        DaySchedule(season="high", day_type=DayType.SUNDAY, ranges=day(49))


def test_a_calendar_has_at_most_12_seasons() -> None:
    assert len(CALENDAR.seasons) <= 12
    with pytest.raises(ValidationError):
        TouCalendar(seasons=CALENDAR.seasons * 7, schedules=CALENDAR.schedules)
