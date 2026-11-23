"""Time-of-use energy priced from kWh per period (P4-7, ADR-0016). Values are fixtures.

The fixture calendar has a "high" season (1 June to 31 August) and a "low" one; the fixture
rates are, in cents per kWh, high: peak 500, standard 200, off-peak 100; low: peak 300,
standard 150, off-peak 100. The fixture VAT rate is 12.5%.
"""

import json
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    Bill,
    BillingPeriod,
    MonthSoFar,
    PeriodTotal,
    PrepaidNotSupportedError,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    calculate_bill,
    calculate_period,
    calculate_purchase,
)
from munisense.domain.billing.errors import PeriodCrossesSeasonError
from munisense.domain.citations import Cited
from munisense.domain.money import Money, RateUnit, VatRate, VatTable
from munisense.domain.tariffs import (
    CalendarSeason,
    Component,
    DayType,
    SeasonDates,
    TariffVersion,
    TouCalendar,
    TouPeriod,
    TouRate,
    UndefinedPeriodError,
)
from support.builders import (
    FIXTURE_STATUS,
    FIXTURE_TOU_CENTS,
    cited_date,
    cited_decimal,
    cited_rate,
    fixture_blocks,
    fixture_calendar,
    fixture_citation,
    fixture_export_credit,
    fixture_fixed,
    fixture_flat,
    fixture_free_basic,
    fixture_levy,
    fixture_season,
    fixture_seasonal,
    fixture_tou_energy,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
CALENDAR = fixture_calendar()
JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
JANUARY = BillingPeriod(start=date(2027, 1, 1), end=date(2027, 2, 1))
PEAK, STANDARD, OFF_PEAK = TouPeriod.PEAK, TouPeriod.STANDARD, TouPeriod.OFF_PEAK


def used(peak: str, standard: str, off_peak: str) -> TimeOfUseBuckets:
    return TimeOfUseBuckets(
        used_kwh={PEAK: Decimal(peak), STANDARD: Decimal(standard), OFF_PEAK: Decimal(off_peak)}
    )


def tou_version(
    *extra: Component, start: date = date(2026, 7, 1), end: date = date(2027, 7, 1)
) -> TariffVersion:
    return fixture_version(
        fixture_tou_energy(), *extra, start=start, end=end, tou_calendar=CALENDAR
    )


def amounts(bill: Bill) -> dict[str, str]:
    return {line.description: str(line.amount.rand) for line in bill.lines}


# ------------------------------------------------------------------------- pricing


def test_each_period_is_priced_at_its_seasons_rate() -> None:
    # high season (July): 100 x R5.00 + 200 x R2.00 + 300 x R1.00 = R1,200.00
    # VAT 12.5% on R1,200.00 = R150.00; total R1,350.00
    bill = calculate_bill(tou_version(), JULY, used("100", "200", "300"), VAT)
    assert amounts(bill) == {
        "high demand season: peak kWh": "500.00",
        "high demand season: standard kWh": "400.00",
        "high demand season: off-peak kWh": "300.00",
    }
    assert bill.subtotal.rand == Decimal("1200.00")
    assert bill.vat.rand == Decimal("150.00")
    assert bill.total.rand == Decimal("1350.00")
    assert bill.consumption_kwh == Decimal(600)


def test_the_low_season_has_its_own_rates() -> None:
    # 100 x R3.00 + 200 x R1.50 + 300 x R1.00 = R900.00
    bill = calculate_bill(tou_version(), JANUARY, used("100", "200", "300"), VAT)
    assert bill.subtotal.rand == Decimal("900.00")


def test_other_charges_are_priced_on_the_total_kwh() -> None:
    """A per-kWh charge with no time of use (like Eskom's legacy charge) uses all kWh."""
    legacy = fixture_flat("10", name="legacy")  # R0.10 x 600 kWh = R60.00
    bill = calculate_bill(tou_version(legacy), JULY, used("100", "200", "300"), VAT)
    assert amounts(bill)["all kWh"] == "60.00"
    assert bill.subtotal.rand == Decimal("1260.00")


def test_a_period_with_no_use_has_no_line() -> None:
    bill = calculate_bill(tou_version(), JULY, used("0", "200", "300"), VAT)
    assert "high demand season: peak kWh" not in amounts(bill)


# ------------------------------------------------------------------------- refusals


def test_a_period_total_cannot_price_a_time_of_use_tariff() -> None:
    with pytest.raises(UnsupportedConsumptionError, match="priced by time of use"):
        calculate_bill(tou_version(), JULY, PeriodTotal(kwh=Decimal(600)), VAT)


def test_kwh_per_period_price_only_a_time_of_use_tariff() -> None:
    with pytest.raises(UnsupportedConsumptionError, match="price only a tariff priced by time"):
        calculate_bill(fixture_version(fixture_flat("100")), JULY, used("1", "1", "1"), VAT)


def test_an_absent_period_is_never_read_as_zero_use() -> None:
    profile = TimeOfUseBuckets(used_kwh={PEAK: Decimal(100), OFF_PEAK: Decimal(300)})
    with pytest.raises(UnsupportedConsumptionError, match="missing: standard; give 0"):
        calculate_bill(tou_version(), JULY, profile, VAT)


def test_exported_kwh_are_refused_until_the_export_credit_exists() -> None:
    profile = TimeOfUseBuckets(
        used_kwh={PEAK: Decimal(1), STANDARD: Decimal(1), OFF_PEAK: Decimal(1)},
        exported_kwh={PEAK: Decimal(1)},
    )
    with pytest.raises(UnsupportedConsumptionError, match="export credit"):
        calculate_bill(tou_version(), JULY, profile, VAT)


def _two_period_calendar() -> TouCalendar:
    """No standard period in any season."""
    day = ((7 * 60, OFF_PEAK), (9 * 60, PEAK), (24 * 60, OFF_PEAK))
    hours: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(DayType, day)
    return fixture_calendar(hours, hours)


def test_a_period_the_calendar_does_not_define_is_refused() -> None:
    cents = {k: v for k, v in FIXTURE_TOU_CENTS.items() if k[1] != STANDARD}
    version = fixture_version(fixture_tou_energy(cents), tou_calendar=_two_period_calendar())
    with pytest.raises(UndefinedPeriodError, match="standard"):
        calculate_bill(version, JULY, used("1", "1", "1"), VAT)


def test_a_rate_is_needed_for_every_period_of_every_season() -> None:
    cents = {k: v for k, v in FIXTURE_TOU_CENTS.items() if k != ("low", PEAK)}
    with pytest.raises(ValidationError, match="no rate for peak in the season 'low'"):
        fixture_version(fixture_tou_energy(cents), tou_calendar=CALENDAR)


def test_a_rate_for_a_period_the_season_lacks_is_refused() -> None:
    with pytest.raises(ValidationError, match="rate for standard in the season 'high'"):
        fixture_version(fixture_tou_energy(), tou_calendar=_two_period_calendar())


def test_a_time_of_use_charge_needs_a_calendar() -> None:
    assert fixture_tou_energy().needs_calendar
    with pytest.raises(ValidationError, match="need a time-of-use calendar"):
        fixture_version(fixture_tou_energy())


def test_one_rate_per_season_and_period_and_only_per_kwh() -> None:
    energy = fixture_tou_energy()
    twice = (*energy.rates, energy.rates[0])
    with pytest.raises(ValidationError, match="one rate per season and period"):
        energy.model_validate({**energy.model_dump(), "rates": twice})
    daily = TouRate(season="high", period=PEAK, rate=cited_rate("1", RateUnit.RAND_PER_DAY))
    with pytest.raises(ValidationError, match="priced per R/kWh"):
        energy.model_validate({**energy.model_dump(), "rates": (daily,)})


def test_a_single_bill_across_the_season_change_is_refused() -> None:
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    version = tou_version(start=date(2026, 4, 1))
    with pytest.raises(PeriodCrossesSeasonError, match="time-of-use calendar"):
        calculate_bill(version, period, used("31", "62", "93"), VAT)


def test_prepaid_purchases_on_a_time_of_use_tariff_are_refused() -> None:
    with pytest.raises(PrepaidNotSupportedError, match="priced by time of use"):
        calculate_purchase(
            tou_version(),
            date(2026, 7, 1),
            Money(rand=Decimal(100)),
            MonthSoFar(purchases=0, kwh=Decimal(0)),
            VAT,
        )


# ------------------------------------------------------------------ across a season change


def test_a_period_across_1_june_is_split_and_each_part_uses_its_season() -> None:
    """15 May to 15 June: 17 days in the low season, 14 in the high. Each period's kWh are
    shared by days (cumulative factor 17/31 = 0.548387, rounded at the fixture's
    millionths): peak 31 kWh -> 16.999997 (low) and 14.000003 (high).

    Low part:  peak 16.999997 x R3.00 = 50.999991 -> 51.00; standard 33.999994 x R1.50 =
    50.999991 -> 51.00; off-peak 50.999991 x R1.00 -> 51.00; subtotal R153.00.
    High part: peak 14.000003 x R5.00 = 70.000015 -> 70.00; standard 28.000006 x R2.00 =
    56.000012 -> 56.00; off-peak 42.000009 x R1.00 -> 42.00; subtotal R168.00."""
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    version = tou_version(start=date(2026, 4, 1))
    bill = calculate_period([version], period, used("31", "62", "93"), VAT)
    low, high = bill.parts
    assert low.period.end == high.period.start == date(2026, 6, 1)
    assert amounts(low) == {
        "low demand season: peak kWh": "51.00",
        "low demand season: standard kWh": "51.00",
        "low demand season: off-peak kWh": "51.00",
    }
    assert amounts(high) == {
        "high demand season: peak kWh": "70.00",
        "high demand season: standard kWh": "56.00",
        "high demand season: off-peak kWh": "42.00",
    }
    assert next(line for line in high.lines if "peak kWh" in line.description).quantity == Decimal(
        "14.000003"
    )
    assert (low.subtotal.rand, high.subtotal.rand) == (Decimal("153.00"), Decimal("168.00"))
    assert sum(p.consumption_kwh for p in bill.parts) == bill.consumption_kwh == Decimal(186)
    assert "time_of_use_shared_across_seasons" in {w.code for w in bill.warnings}


def test_a_split_inside_one_season_does_not_warn_about_seasons() -> None:
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 15))
    bill = calculate_period([tou_version()], period, used("31", "62", "93"), VAT)
    assert len(bill.parts) == 2
    assert "time_of_use_shared_across_seasons" not in {w.code for w in bill.warnings}


def test_a_vat_change_splits_time_of_use_kwh_too() -> None:
    """VAT 12.5% until 1 August 2026, 15% from then; 15 July to 15 August (high season):
    July part peak 16.999997 x R5.00 = 84.999985 -> 85.00, standard 33.999994 x R2.00 ->
    68.00, off-peak 50.999991 -> 51.00: R204.00, VAT 12.5% R25.50; August part peak
    14.000003 x R5.00 -> 70.00, standard 28.000006 x R2.00 -> 56.00, off-peak 42.000009 ->
    42.00: R168.00, VAT 15% R25.20."""
    table = VatTable(
        rates=(
            VatRate(
                start_cited=cited_date(date(2000, 1, 1)),
                end_cited=cited_date(date(2026, 8, 1)),
                percent=cited_decimal("12.5"),
            ),
            VatRate(
                start_cited=cited_date(date(2026, 8, 1)),
                end_cited=None,
                percent=cited_decimal("15"),
            ),
        )
    )
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 15))
    july, august = calculate_period([tou_version()], period, used("31", "62", "93"), table).parts
    assert (july.subtotal.rand, july.vat.rand) == (Decimal("204.00"), Decimal("25.50"))
    assert (august.subtotal.rand, august.vat.rand) == (Decimal("168.00"), Decimal("25.20"))


def test_kwh_for_a_period_a_reached_season_lacks_cannot_be_shared() -> None:
    """Sharing by days would put standard kWh in the low part, which has no standard."""
    no_standard = ((7 * 60, OFF_PEAK), (9 * 60, PEAK), (24 * 60, OFF_PEAK))
    low: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(DayType, no_standard)
    cents = {k: v for k, v in FIXTURE_TOU_CENTS.items() if k != ("low", STANDARD)}
    version = fixture_version(
        fixture_tou_energy(cents),
        tou_calendar=fixture_calendar(low=low),
        start=date(2026, 4, 1),
        end=date(2027, 4, 1),
    )
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    with pytest.raises(UndefinedPeriodError, match="standard cannot be shared over this period"):
        calculate_period([version], period, used("1", "1", "1"), VAT)
    assert calculate_period([version], period, used("1", "0", "1"), VAT).parts


def test_only_versions_that_price_a_part_are_asked_about_the_consumption() -> None:
    """A later version of a plain tariff, outside the period, does not refuse kWh per
    period for the time-of-use version that prices it."""
    tou = tou_version(start=date(2026, 7, 1), end=date(2026, 10, 1))
    later = fixture_version(fixture_flat("100"), start=date(2026, 10, 1), end=None)
    bill = calculate_period([tou, later], JULY, used("1", "1", "1"), VAT)
    assert bill.subtotal.rand == Decimal("8.00")


def test_a_long_period_on_a_one_season_calendar_does_no_unbounded_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One season covers every day, so no day is checked; with two seasons, a period of
    more than 366 days crosses one without checking each day."""
    whole_year = SeasonDates(start_month=1, start_day=1, end_month=12, end_day=31)
    season = CalendarSeason(
        name="high",
        label=CALENDAR.seasons[0].label,
        dates=Cited[SeasonDates](
            value=whole_year, citation=fixture_citation("all year"), status=FIXTURE_STATUS
        ),
    )
    one_season = TouCalendar(
        seasons=(season,),
        schedules=tuple(s for s in CALENDAR.schedules if s.season == "high"),
        holidays=CALENDAR.holidays,
    )
    cents = {k: v for k, v in FIXTURE_TOU_CENTS.items() if k[0] == "high"}
    version = fixture_version(
        fixture_tou_energy(cents), start=date(2026, 7, 1), end=None, tou_calendar=one_season
    )
    long_period = BillingPeriod(start=date(2026, 7, 1), end=date(9999, 1, 1))
    lookups: list[date] = []
    real = TouCalendar.season_for

    def counted(self: TouCalendar, day: date) -> CalendarSeason:
        lookups.append(day)
        return real(self, day)

    monkeypatch.setattr(TouCalendar, "season_for", counted)
    bill = calculate_bill(version, long_period, used("1", "1", "1"), VAT)
    assert bill.subtotal.rand == Decimal("8.00")
    assert len(lookups) < 10  # a handful of lookups, not one per day of ~2.9 million
    lookups.clear()
    with pytest.raises(PeriodCrossesSeasonError):
        calculate_bill(
            tou_version(start=date(2026, 7, 1), end=date(2027, 8, 1)),
            BillingPeriod(start=date(2026, 7, 1), end=date(2027, 7, 3)),  # 367 days
            used("1", "1", "1"),
            VAT,
        )
    assert len(lookups) < 10  # refused without reading each of the 367 days


def test_every_component_priced_by_period_needs_a_calendar() -> None:
    """Pricing by time of use and needing a calendar must not drift apart: only the
    time-of-use energy charge needs one, and every member of the union is checked."""
    instances = {
        "fixed_charge": fixture_fixed("1"),
        "flat_energy": fixture_flat("1"),
        "block_energy": fixture_blocks((None, "1")),
        "seasonal_energy": fixture_seasonal(fixture_season("all", (1, 1), (12, 31), (None, "1"))),
        "time_of_use_energy": fixture_tou_energy(),
        "export_credit": fixture_export_credit(),
        "levy": fixture_levy("1"),
        "free_basic_allocation": fixture_free_basic("50"),
    }
    union = get_args(get_args(Component)[0])
    kinds = {get_args(m.model_fields["kind"].annotation)[0] for m in union}
    assert kinds == set(instances)
    assert {k for k, c in instances.items() if c.needs_calendar} == {
        "time_of_use_energy",
        "export_credit",
    }


def test_a_free_basic_allocation_cannot_target_time_of_use_energy() -> None:
    with pytest.raises(ValidationError):
        fixture_version(
            fixture_tou_energy(),
            fixture_free_basic("50", energy_component="tou_energy"),
            tou_calendar=CALENDAR,
        )


def test_a_missing_rate_is_refused_wherever_a_version_is_read() -> None:
    """The publish step, the publication guards and the loader all read a version with
    `TariffVersion` validation, so the rate checks run there too (by construction)."""
    text = tou_version().model_dump_json()
    data = json.loads(text)
    data["components"][0]["rates"] = [
        r for r in data["components"][0]["rates"] if (r["season"], r["period"]) != ("low", "peak")
    ]
    with pytest.raises(ValidationError, match="no rate for peak in the season 'low'"):
        TariffVersion.model_validate_json(json.dumps(data))


def test_use_in_a_period_the_bills_season_lacks_is_refused() -> None:
    """The high season has a standard period and the low one does not: standard kWh in a
    January bill cannot be priced, even though the calendar defines standard somewhere."""
    no_standard = ((7 * 60, OFF_PEAK), (9 * 60, PEAK), (24 * 60, OFF_PEAK))
    low: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(DayType, no_standard)
    calendar = fixture_calendar(low=low)
    cents = {k: v for k, v in FIXTURE_TOU_CENTS.items() if k != ("low", STANDARD)}
    version = fixture_version(
        fixture_tou_energy(cents), tou_calendar=calendar, end=date(2027, 7, 1)
    )
    assert calculate_bill(version, JANUARY, used("1", "0", "1"), VAT).subtotal.rand > 0
    with pytest.raises(UndefinedPeriodError, match="standard, which the low season does not have"):
        calculate_bill(version, JANUARY, used("1", "1", "1"), VAT)


def test_a_calendar_without_time_of_use_charges_still_prices_a_period_total() -> None:
    """A calendar may carry the seasons of a seasonal charge only (TD-11); such a tariff is
    not priced by time of use, so a period total prices it as before."""
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300")),
        fixture_season("low", (9, 1), (5, 31), (None, "200")),
    )
    version = fixture_version(seasonal, tou_calendar=CALENDAR)
    bill = calculate_bill(version, JULY, PeriodTotal(kwh=Decimal(10)), VAT)
    assert bill.subtotal.rand == Decimal("30.00")  # 10 kWh x R3.00 (high season)
    period = BillingPeriod(start=date(2026, 8, 15), end=date(2026, 9, 15))
    assert calculate_period([version], period, PeriodTotal(kwh=Decimal(31)), VAT).parts
