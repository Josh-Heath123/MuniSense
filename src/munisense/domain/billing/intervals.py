"""Interval readings classified into time-of-use buckets (P4-10, ADR-0016 point 4).

Each interval is put in its part of the billing period (by its day), and in that part's
calendar season, day type and time-of-use period. A day's schedule (and its day type,
holidays included) is looked up once per day, and each schedule's minute table is built
once per profile. An interval any minute of which is in another period is refused (it
cannot be split). The buckets of a part are exact sums of its readings; they are priced as they
are, never shared again by days.

Readings show when people are at home: nothing here stores or logs them, and a refusal
names at most an interval's position, never a time or a kWh figure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from munisense.domain.billing.consumption import SAST, IntervalReadings
from munisense.domain.billing.errors import IntervalReadingsError
from munisense.domain.money import exact
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import DaySchedule, DayType, TariffVersion, TouPeriod
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
        raise IntervalReadingsError(msg, "readings_do_not_cover_period")
    per_day = MINUTES_IN_A_DAY // readings.minutes
    tables: dict[tuple[int, str, DayType], _Table] = {}  # built once per schedule
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
            key = (id(calendar), schedule.season, schedule.day_type)
            table = tables.get(key)
            if table is None:
                table = tables[key] = _table(schedule)
            first = (day - period.start).days * per_day
            for slot in range(per_day):
                index = first + slot
                reading = readings.readings[index]
                start_minute = slot * readings.minutes
                if table.run_end[start_minute] < start_minute + readings.minutes:
                    # Some minute of the interval is in another period (even a period that
                    # starts and ends inside it): the reading cannot be split, so refuse.
                    msg = f"interval {index}: it crosses a time-of-use period boundary"
                    raise IntervalReadingsError(msg, "interval_crosses_period_boundary")
                kind = table.period[start_minute]
                with exact():
                    used[kind] += reading.used_kwh
                    if exporting:
                        exported[kind] += reading.exported_kwh
        result.append((used, exported))
    return result


@dataclass(frozen=True)
class _Table:
    """For each minute of a day: its period, and the first minute after it in another
    period (the end of its run; 1,440 at the end of the day)."""

    period: list[TouPeriod]
    run_end: list[int]


def _table(schedule: DaySchedule) -> _Table:
    period = [schedule.period_at(minute) for minute in range(MINUTES_IN_A_DAY)]
    run_end = [MINUTES_IN_A_DAY] * MINUTES_IN_A_DAY
    for minute in range(MINUTES_IN_A_DAY - 2, -1, -1):
        same = period[minute] is period[minute + 1]
        run_end[minute] = run_end[minute + 1] if same else minute + 1
    return _Table(period, run_end)


def total_used(readings: IntervalReadings) -> Decimal:
    with exact():
        return sum((r.used_kwh for r in readings.readings), Decimal(0))
