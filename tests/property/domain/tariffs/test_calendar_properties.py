"""Every minute falls in exactly one season, day type and period (P4-5).

The answers are compared with a brute-force count over the calendar's own ranges and
season dates, independent of how `TouCalendar` looks them up. Hours are fixtures.
"""

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from munisense.domain.tariffs import DayType, TouCalendar, TouPeriod
from support.builders import fixture_calendar

LEAP_YEAR = 2028


def _brute_force(calendar: TouCalendar, day: date, minute: int) -> tuple[str, DayType, TouPeriod]:
    seasons = [s.name for s in calendar.seasons if s.dates.value.contains(day)]
    assert len(seasons) == 1
    day_type = (DayType.WEEKDAY,) * 5 + (DayType.SATURDAY, DayType.SUNDAY)
    schedules = [
        s
        for s in calendar.schedules
        if (s.season, s.day_type) == (seasons[0], day_type[day.weekday()])
    ]
    assert len(schedules) == 1
    periods = [
        r.value.period
        for r in schedules[0].ranges
        if r.value.start_minute <= minute < r.value.end_minute
    ]
    assert len(periods) == 1
    return seasons[0], day_type[day.weekday()], periods[0]


def test_every_minute_of_a_leap_year_has_one_season_day_type_and_period() -> None:
    calendar = fixture_calendar()
    day = date(LEAP_YEAR, 1, 1)
    minutes = 0
    while day.year == LEAP_YEAR:
        season, day_type = calendar.season_for(day).name, calendar.day_type(day)
        schedule = calendar.schedule_for(day)
        for minute in range(24 * 60):
            assert _brute_force(calendar, day, minute) == (
                season,
                day_type,
                schedule.period_at(minute),
            )
            minutes += 1
        day += timedelta(days=1)
    assert minutes == 366 * 24 * 60


cuts = st.lists(st.integers(1, 24 * 60 - 1), max_size=12, unique=True).map(sorted)
periods = st.sampled_from(list(TouPeriod))
days = st.dates(date(LEAP_YEAR, 1, 1), date(LEAP_YEAR, 12, 31))


@st.composite
def calendars(draw: st.DrawFn) -> TouCalendar:
    """A calendar with random hours for each day type (both seasons share them)."""
    hours = {}
    for day_type in DayType:
        ends = [*draw(cuts), 24 * 60]
        hours[day_type] = tuple((end, draw(periods)) for end in ends)
    return fixture_calendar(hours)


@settings(max_examples=200)
@given(calendars(), days, st.integers(0, 24 * 60 - 1))
def test_any_calendar_puts_each_minute_in_exactly_one_period(
    calendar: TouCalendar, day: date, minute: int
) -> None:
    season, day_type, period = _brute_force(calendar, day, minute)
    assert calendar.season_for(day).name == season
    assert calendar.day_type(day) == day_type
    assert calendar.period_for(day, minute) == period
