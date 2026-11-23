"""The buckets of interval readings add up to the readings exactly (P4-10). Fixtures."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from munisense.domain.billing import BillingPeriod, IntervalReading, IntervalReadings
from munisense.domain.billing.intervals import classify
from munisense.domain.tariffs import TouPeriod
from support.builders import fixture_calendar, fixture_tou_energy, fixture_version

SAST = timezone(timedelta(hours=2))
CALENDAR = fixture_calendar()
VERSION = fixture_version(fixture_tou_energy(), start=date(2026, 4, 1), tou_calendar=CALENDAR)
kwh = st.integers(0, 100_000).map(lambda k: Decimal(k).scaleb(-3))


@settings(max_examples=40)
@given(
    st.dates(date(2026, 5, 1), date(2026, 9, 28)),
    st.integers(1, 3),
    st.sampled_from([15, 30, 60]),
    st.data(),
)
def test_buckets_add_up_to_the_readings_and_match_the_calendar(
    first: date, days: int, minutes: int, data: st.DataObject
) -> None:
    count = days * 24 * 60 // minutes
    values = data.draw(st.lists(kwh, min_size=count, max_size=count))
    start = datetime(first.year, first.month, first.day, tzinfo=SAST)
    profile = IntervalReadings(
        minutes=minutes,  # type: ignore[arg-type]
        readings=tuple(
            IntervalReading(start=start + timedelta(minutes=minutes * i), used_kwh=v)
            for i, v in enumerate(values)
        ),
    )
    period = BillingPeriod(start=first, end=first + timedelta(days=days))
    ((used, _),) = classify(profile, period, [(period, VERSION)])
    assert sum(used.values(), Decimal(0)) == sum(values, Decimal(0))
    expected: dict[TouPeriod, Decimal] = dict.fromkeys(CALENDAR.periods, Decimal(0))
    for i, v in enumerate(values):
        moment = start + timedelta(minutes=minutes * i)
        expected[CALENDAR.period_for(moment.date(), moment.hour * 60 + moment.minute)] += v
    assert used == expected
