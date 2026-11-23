"""Interval readings classified by the calendar and priced (P4-10, ADR-0016 point 4).

Hours and rates are the fixtures' (made up). High season, weekday: off-peak 00:00-06:00,
standard 06:00-18:00, peak 18:00-21:00, off-peak 21:00-24:00; rates (c/kWh) peak 500,
standard 200, off-peak 100. VAT 12.5%.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.base import DomainError
from munisense.domain.billing import (
    BillingPeriod,
    IntervalReading,
    IntervalReadings,
    NonMonthlyPeriodError,
    UnsupportedConsumptionError,
    calculate_bill,
    calculate_period,
)
from munisense.domain.billing.consumption import MAX_INTERVALS
from munisense.domain.billing.errors import IntervalReadingsError
from munisense.domain.billing.intervals import classify
from munisense.domain.tariffs import (
    DaySchedule,
    DayType,
    ExportCap,
    HolidayCoverageError,
    TariffVersion,
    TouCalendar,
    TouPeriod,
)
from support.builders import (
    fixture_billing_policy,
    fixture_calendar,
    fixture_export_credit,
    fixture_flat,
    fixture_holiday_list,
    fixture_tou_energy,
    fixture_vat_table,
    fixture_version,
)

SAST = timezone(timedelta(hours=2))
VAT = fixture_vat_table()
CALENDAR = fixture_calendar()


def tou_version(start: date = date(2026, 4, 1)) -> TariffVersion:
    return fixture_version(fixture_tou_energy(), start=start, tou_calendar=CALENDAR)


def readings(first: date, days: int, minutes: int = 60, kwh: str = "1") -> IntervalReadings:
    start = datetime(first.year, first.month, first.day, tzinfo=SAST)
    count = days * 24 * 60 // minutes
    return IntervalReadings(
        minutes=minutes,  # type: ignore[arg-type]
        readings=tuple(
            IntervalReading(start=start + timedelta(minutes=minutes * i), used_kwh=Decimal(kwh))
            for i in range(count)
        ),
    )


def day(first: date, days: int = 1) -> BillingPeriod:
    return BillingPeriod(start=first, end=first + timedelta(days=days))


# ------------------------------------------------------------------------ pricing


def test_a_wednesday_of_hourly_readings_by_hand() -> None:
    """15 July 2026 (a high-season Wednesday), 1 kWh each hour: 9 off-peak, 12 standard
    and 3 peak hours: 3 x R5.00 + 12 x R2.00 + 9 x R1.00 = R48.00."""
    bill = calculate_bill(
        tou_version(), day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1), VAT
    )
    assert {line.description: line.quantity for line in bill.lines} == {
        "high demand season: peak kWh": Decimal(3),
        "high demand season: standard kWh": Decimal(12),
        "high demand season: off-peak kWh": Decimal(9),
    }
    assert bill.subtotal.rand == Decimal("48.00")
    assert bill.consumption_kwh == Decimal(24)


@pytest.mark.parametrize("minutes", [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60])
def test_every_interval_length_that_divides_an_hour_gives_the_same_buckets(minutes: int) -> None:
    """`minutes` kWh in each interval is exactly 60 kWh an hour at every length: 180 kWh
    peak, 720 standard and 540 off-peak on the Wednesday, R2,880.00."""
    bill = calculate_bill(
        tou_version(),
        day(date(2026, 7, 15)),
        readings(date(2026, 7, 15), 1, minutes, str(minutes)),
        VAT,
    )
    assert {line.description: line.quantity for line in bill.lines} == {
        "high demand season: peak kWh": Decimal(180),
        "high demand season: standard kWh": Decimal(720),
        "high demand season: off-peak kWh": Decimal(540),
    }
    assert bill.subtotal.rand == Decimal("2880.00")


def test_a_listed_holiday_is_priced_as_its_listed_day_type() -> None:
    """15 July 2026 listed as a Sunday (made up): every hour off-peak: 24 x R1.00."""
    holidays = fixture_holiday_list(
        (date(2026, 4, 1), date(2027, 7, 1)), (date(2026, 7, 15), DayType.SUNDAY)
    )
    version = fixture_version(
        fixture_tou_energy(),
        start=date(2026, 4, 1),
        end=date(2027, 4, 1),
        tou_calendar=fixture_calendar(holidays=holidays),
    )
    bill = calculate_bill(version, day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1), VAT)
    assert bill.subtotal.rand == Decimal("24.00")


def test_a_holiday_coverage_error_is_a_refusal() -> None:
    """A day outside a holiday list's window is refused as a `DomainError`. Pricing cannot
    meet one: a version with a list must be covered by it for every day
    (`test_a_holiday_list_must_cover_every_day_of_the_version`, P4-6) and a bill lies
    inside its version; the calendar shows the refusal directly."""
    holidays = fixture_holiday_list(
        (date(2026, 4, 1), date(2027, 7, 1)), (date(2026, 7, 15), DayType.SUNDAY)
    )
    calendar = fixture_calendar(holidays=holidays)
    with pytest.raises(HolidayCoverageError) as caught:
        calendar.period_for(date(2030, 1, 1), 0)
    assert isinstance(caught.value, DomainError)


def test_across_a_season_change_each_part_uses_its_own_readings_and_season() -> None:
    """31 May (low season) and 1 June (high), 1 kWh each hour: the parts are priced from
    their own day's readings, never shared by days, and no sharing warning is given.
    31 May 2026 is a Sunday (low season: standard 17:00-19:00, off-peak otherwise):
    22 x R1.00 + 2 x R1.50 = R25.00. 1 June is a Monday:
    3 x R5.00 + 12 x R2.00 + 9 x R1.00 = R48.00."""
    bill = calculate_period(
        [tou_version()], day(date(2026, 5, 31), 2), readings(date(2026, 5, 31), 2), VAT
    )
    low, high = bill.parts
    assert (low.subtotal.rand, high.subtotal.rand) == (Decimal("25.00"), Decimal("48.00"))
    assert (low.consumption_kwh, high.consumption_kwh) == (Decimal(24), Decimal(24))
    assert "time_of_use_shared_across_seasons" not in {w.code for w in bill.warnings}


def test_across_a_month_change_each_part_keeps_its_own_readings() -> None:
    """31 July (Friday, 2 kWh an hour) and 1 August (Saturday, 1 kWh an hour): the July
    part has 48 kWh and the August part 24, as read; days do not share them out."""
    start = datetime(2026, 7, 31, tzinfo=SAST)
    profile = IntervalReadings(
        minutes=60,
        readings=tuple(
            IntervalReading(start=start + timedelta(hours=i), used_kwh=Decimal(2 if i < 24 else 1))
            for i in range(48)
        ),
    )
    bill = calculate_period([tou_version()], day(date(2026, 7, 31), 2), profile, VAT)
    assert [part.consumption_kwh for part in bill.parts] == [Decimal(48), Decimal(24)]


# ------------------------------------------------------------------------ refusals


def test_readings_must_cover_the_billing_period_exactly() -> None:
    for period, profile in (
        (day(date(2026, 7, 15), 2), readings(date(2026, 7, 15), 1)),
        (day(date(2026, 7, 15)), readings(date(2026, 7, 14), 1)),
    ):
        with pytest.raises(
            IntervalReadingsError, match="cover the billing period exactly"
        ) as caught:
            calculate_bill(tou_version(), period, profile, VAT)
        assert caught.value.code == "readings_do_not_cover_period"


def test_an_interval_across_a_period_boundary_is_refused_by_its_position_only() -> None:
    """A made-up calendar with standard starting at 06:30: an hourly reading from 06:00
    crosses it."""
    weekday = ((6 * 60 + 30, TouPeriod.OFF_PEAK), (24 * 60, TouPeriod.STANDARD))
    plain = ((24 * 60, TouPeriod.OFF_PEAK),)
    hours = {DayType.WEEKDAY: weekday, DayType.SATURDAY: plain, DayType.SUNDAY: plain}
    cents = {
        (season, period): "100"
        for season in ("high", "low")
        for period in (TouPeriod.OFF_PEAK, TouPeriod.STANDARD)
    }
    version = fixture_version(
        fixture_tou_energy(cents),
        start=date(2026, 4, 1),
        tou_calendar=fixture_calendar(hours, hours),
    )
    with pytest.raises(
        IntervalReadingsError, match=r"^interval 6: it crosses a time-of-use"
    ) as caught:
        calculate_bill(
            version, day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1, kwh="98765"), VAT
        )
    assert "98765" not in str(caught.value) + repr(caught.value.args)
    assert "2026" not in str(caught.value) + repr(caught.value.args)
    assert caught.value.code == "interval_crosses_period_boundary"


def test_a_period_wholly_inside_one_interval_is_refused() -> None:
    """Standard for ten minutes, 07:25 to 07:35, inside the 07:00 hour: the hour starts
    and ends off-peak, but cannot be billed as off-peak (both reviews of P4-10). Five-minute
    readings of the same day are priced."""
    weekday = (
        (7 * 60 + 25, TouPeriod.OFF_PEAK),
        (7 * 60 + 35, TouPeriod.STANDARD),
        (24 * 60, TouPeriod.OFF_PEAK),
    )
    plain = ((24 * 60, TouPeriod.OFF_PEAK),)
    hours = {DayType.WEEKDAY: weekday, DayType.SATURDAY: plain, DayType.SUNDAY: plain}
    cents = {
        (season, period): "100"
        for season in ("high", "low")
        for period in (TouPeriod.OFF_PEAK, TouPeriod.STANDARD)
    }
    version = fixture_version(
        fixture_tou_energy(cents),
        start=date(2026, 4, 1),
        tou_calendar=fixture_calendar(hours, hours),
    )
    with pytest.raises(IntervalReadingsError, match=r"^interval 7: it crosses") as caught:
        calculate_bill(version, day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1), VAT)
    assert caught.value.code == "interval_crosses_period_boundary"
    five_minutes = calculate_bill(
        version, day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1, 5, "5"), VAT
    )
    assert five_minutes.consumption_kwh == Decimal(24 * 60)


def test_interval_readings_price_only_a_tariff_priced_by_time_of_use() -> None:
    plain = fixture_version(fixture_flat("100"))
    with pytest.raises(UnsupportedConsumptionError, match="priced by time of use"):
        calculate_bill(plain, day(date(2026, 7, 15)), readings(date(2026, 7, 15), 1), VAT)


def test_exports_on_a_tariff_without_an_export_credit_are_refused() -> None:
    start = datetime(2026, 7, 15, tzinfo=SAST)
    profile = IntervalReadings(
        minutes=60,
        readings=tuple(
            IntervalReading(
                start=start + timedelta(hours=i), used_kwh=Decimal(1), exported_kwh=Decimal(i == 12)
            )
            for i in range(24)
        ),
    )
    with pytest.raises(UnsupportedConsumptionError, match="no export credit"):
        calculate_bill(tou_version(), day(date(2026, 7, 15)), profile, VAT)


# ---------------------------------------------------------------------- the model


def _model(starts: list[datetime], minutes: int = 60) -> IntervalReadings:
    return IntervalReadings(
        minutes=minutes,  # type: ignore[arg-type]
        readings=tuple(IntervalReading(start=s, used_kwh=Decimal("98765")) for s in starts),
    )


ZERO = datetime(2026, 7, 15, tzinfo=SAST)


@pytest.mark.parametrize(
    ("starts", "code", "message"),
    [
        ([ZERO, ZERO + timedelta(hours=2)], "interval_gap", "interval 1: a gap before it"),
        ([ZERO, ZERO], "interval_overlap", "interval 1: it overlaps the one before"),
        (
            [ZERO + timedelta(minutes=15)],
            "interval_off_grid",
            "interval 0: it does not start on the interval grid",
        ),
        (
            [ZERO + timedelta(seconds=1)],
            "interval_off_grid",
            "interval 0: it does not start on the interval grid",
        ),
        (
            [datetime(2026, 7, 15, tzinfo=UTC)],
            "interval_not_sast",
            r"interval 0: its start is not in South African Standard Time \(\+02:00\)",
        ),
    ],
)
def test_the_readings_refuse_gaps_overlaps_grids_and_zones_by_position_only(
    starts: list[datetime], code: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message) as caught:
        _model(starts)
    assert [e["type"] for e in caught.value.errors()] == [code]
    shown = str(caught.value) + repr(caught.value.args)
    assert "98765" not in shown
    assert "2026-07-15" not in shown
    assert "2026, 7, 15" not in shown


def test_a_naive_start_or_a_length_that_does_not_divide_an_hour_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        _model([datetime(2026, 7, 15)])  # noqa: DTZ001 - the point of the test
    assert {e["type"] for e in caught.value.errors()} == {"timezone_aware"}
    with pytest.raises(ValidationError) as caught:
        _model([ZERO], minutes=7)
    assert {e["type"] for e in caught.value.errors()} == {"literal_error"}


def test_there_are_at_most_max_intervals_readings() -> None:
    """A 31-day month of 1-minute readings is the most (44,640)."""
    assert MAX_INTERVALS == 31 * 24 * 60
    one_more = [
        {"start": (ZERO + timedelta(minutes=i)).isoformat(), "used_kwh": "0"}
        for i in range(MAX_INTERVALS + 1)
    ]
    with pytest.raises(ValidationError) as caught:
        IntervalReadings.model_validate({"minutes": 1, "readings": one_more}, strict=False)
    assert ("too_long", ("readings",)) in [(e["type"], e["loc"]) for e in caught.value.errors()]


def test_classification_reads_each_day_schedule_once() -> None:
    """Day types (holidays included) are looked up once per day, not per interval."""
    calls: list[date] = []
    calendar = CALENDAR
    real = type(calendar).schedule_for

    def counted(self: object, d: date) -> object:
        calls.append(d)
        return real(self, d)  # type: ignore[arg-type]

    version = tou_version()
    period = day(date(2026, 7, 15), 2)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(type(calendar), "schedule_for", counted)
        classify(readings(date(2026, 7, 15), 2, minutes=1), period, [(period, version)])
    assert calls == [date(2026, 7, 15), date(2026, 7, 16)]


def test_exports_from_a_month_of_readings_are_credited_per_period() -> None:
    """July 2026, hourly: 1 kWh used each hour, and 0.5 kWh exported at noon each day.
    Noon is standard on weekdays and off-peak at weekends in the fixture's high season.
    July 2026 has 23 weekdays and 8 weekend days: 23 x 0.5 = 11.5 kWh standard at R1.50
    credit = R17.25, and 8 x 0.5 = 4 kWh off-peak at R0.80 = R3.20."""
    version = fixture_version(
        fixture_tou_energy(),
        fixture_export_credit(),
        start=date(2026, 4, 1),
        tou_calendar=CALENDAR,
        billing=fixture_billing_policy(export_cap=ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH),
    )
    start = datetime(2026, 7, 1, tzinfo=SAST)
    profile = IntervalReadings(
        minutes=60,
        readings=tuple(
            IntervalReading(
                start=start + timedelta(hours=i),
                used_kwh=Decimal(1),
                exported_kwh=Decimal("0.5") if i % 24 == 12 else Decimal(0),
            )
            for i in range(31 * 24)
        ),
    )
    bill = calculate_bill(version, day(date(2026, 7, 1), 31), profile, VAT)
    credits = {
        line.description: (line.quantity, line.amount.rand)
        for line in bill.lines
        if line.amount.rand < 0
    }
    assert credits == {
        "high demand season: standard kWh exported, credited": (Decimal("11.5"), Decimal("-17.25")),
        "high demand season: off-peak kWh exported, credited": (Decimal("4.0"), Decimal("-3.20")),
    }


def test_exports_from_readings_over_two_parts_are_refused_for_now() -> None:
    """The P4-8 rule stands for readings too: exports only on one calendar month priced in
    one part (raised at the checkpoint: readings could show each part's use)."""
    version = fixture_version(
        fixture_tou_energy(),
        fixture_export_credit(),
        start=date(2026, 4, 1),
        tou_calendar=CALENDAR,
        billing=fixture_billing_policy(export_cap=ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH),
    )
    start = datetime(2026, 7, 31, tzinfo=SAST)
    profile = IntervalReadings(
        minutes=60,
        readings=tuple(
            IntervalReading(
                start=start + timedelta(hours=i), used_kwh=Decimal(1), exported_kwh=Decimal(1)
            )
            for i in range(48)
        ),
    )
    with pytest.raises(NonMonthlyPeriodError, match="one calendar month priced in one part"):
        calculate_period([version], day(date(2026, 7, 31), 2), profile, VAT)


def test_each_part_is_classified_by_its_own_versions_calendar() -> None:
    """A tariff change on 16 July to a version whose (made-up) calendar is off-peak all day:
    the 15th is priced by the fixture hours (R48.00), the 16th all off-peak (R24.00)."""
    plain = ((24 * 60, TouPeriod.OFF_PEAK),)
    flat_hours: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(DayType, plain)
    cents = {(s, TouPeriod.OFF_PEAK): "100" for s in ("high", "low")}
    first = fixture_version(
        fixture_tou_energy(), start=date(2026, 4, 1), end=date(2026, 7, 16), tou_calendar=CALENDAR
    )
    second = fixture_version(
        fixture_tou_energy(cents),
        start=date(2026, 7, 16),
        tou_calendar=fixture_calendar(flat_hours, flat_hours),
    )
    bill = calculate_period(
        [first, second], day(date(2026, 7, 15), 2), readings(date(2026, 7, 15), 2), VAT
    )
    assert [part.subtotal.rand for part in bill.parts] == [Decimal("48.00"), Decimal("24.00")]


@pytest.mark.slow
def test_a_full_month_of_one_minute_readings_is_classified_with_bounded_work() -> None:
    """The most readings allowed (44,640): every minute of July. Each day's schedule is
    looked up once, and each distinct schedule's minute table built once (`period_at` is
    called 1,440 times per table, not per interval)."""
    profile = readings(date(2026, 7, 1), 31, 1, "0.001")
    calls = {"schedule_for": 0, "period_at": 0}
    schedule_for = TouCalendar.schedule_for
    period_at = DaySchedule.period_at

    def count_schedule(self: TouCalendar, d: date) -> DaySchedule:
        calls["schedule_for"] += 1
        return schedule_for(self, d)

    def count_minute(self: DaySchedule, minute: int) -> TouPeriod:
        calls["period_at"] += 1
        return period_at(self, minute)

    july = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TouCalendar, "schedule_for", count_schedule)
        patch.setattr(DaySchedule, "period_at", count_minute)
        bill = calculate_bill(tou_version(), july, profile, VAT)
    assert len(profile.readings) == MAX_INTERVALS
    assert bill.consumption_kwh == Decimal("44.640")
    assert calls["schedule_for"] == 31
    assert calls["period_at"] == 3 * 1440  # weekday, Saturday and Sunday tables
