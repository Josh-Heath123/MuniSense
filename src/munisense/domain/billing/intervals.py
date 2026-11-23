"""Interval readings classified into time-of-use buckets (P4-10, ADR-0016 point 4).

Each interval is put in its part of the billing period (by its day), and in that part's
calendar season, day type and time-of-use period. A day's schedule (and its day type,
holidays included) is looked up once per day, and each schedule's minutes once per
profile. The buckets of a part are exact sums of its readings; they are priced as they
are, never shared again by days.

Readings show when people are at home: nothing here stores or logs them, and a refusal
names at most an interval's position, never a time or a kWh figure.
"""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from munisense.domain.billing.consumption import SAST, IntervalReadings
from munisense.domain.billing.errors import IntervalReadingsError
from munisense.domain.money import exact
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import DaySchedule, TariffVersion, TouPeriod
from munisense.domain.tariffs.time_of_use import MINUTES_IN_A_DAY

type Buckets = dict[TouPeriod, Decimal]


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=timezone(SAST))


def classify(
    readings: IntervalReadings,
    period: DateRange,
    parts: Sequence[tuple[DateRange, TariffVersion]],
) -> list[tuple[Buckets, Buckets]]:
    """The kWh used and exported per time-of-use period, for each part of the period.

    The readings must cover the billing period exactly, from midnight (SAST) of its first
    day to midnight of its end."""
    if readings.first_start != _midnight(period.start) or readings.end != _midnight(period.end):
        msg = "the readings must cover the billing period exactly, midnight to midnight (SAST)"
        raise IntervalReadingsError(msg)
    per_day = MINUTES_IN_A_DAY // readings.minutes
    minutes_of: dict[int, list[TouPeriod]] = {}  # per schedule (by identity), once
    exporting = any(r.exported_kwh > 0 for r in readings.readings)
    result = []
    for part, version in parts:
        calendar = version.tou_calendar
        if calendar is None:  # pragma: no cover - the callers refuse such a version first
            raise AssertionError
        used: Buckets = dict.fromkeys(calendar.periods, Decimal(0))
        exported: Buckets = dict.fromkeys(calendar.periods, Decimal(0)) if exporting else {}
        for offset in range(part.days):
            day = part.start + timedelta(days=offset)
            schedule = calendar.schedule_for(day)  # once per day: season, day type, holidays
            by_minute = minutes_of.setdefault(id(schedule), _by_minute(schedule))
            first = (day - period.start).days * per_day
            for slot in range(per_day):
                index = first + slot
                reading = readings.readings[index]
                start_minute = slot * readings.minutes
                kind = by_minute[start_minute]
                if by_minute[start_minute + readings.minutes - 1] is not kind:
                    msg = f"interval {index}: it crosses a time-of-use period boundary"
                    raise IntervalReadingsError(msg)
                with exact():
                    used[kind] += reading.used_kwh
                    if exporting:
                        exported[kind] += reading.exported_kwh
        result.append((used, exported))
    return result


def _by_minute(schedule: DaySchedule) -> list[TouPeriod]:
    """The period of each minute of the day."""
    return [schedule.period_at(minute) for minute in range(MINUTES_IN_A_DAY)]


def total_used(readings: IntervalReadings) -> Decimal:
    with exact():
        return sum((r.used_kwh for r in readings.readings), Decimal(0))
