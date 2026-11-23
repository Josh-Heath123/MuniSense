"""Time-of-use energy priced from kWh per period (P4-7, ADR-0016). Values are fixtures.

The fixture calendar has a "high" season (1 June to 31 August) and a "low" one; the fixture
rates are, in cents per kWh, high: peak 500, standard 200, off-peak 100; low: peak 300,
standard 150, off-peak 100. The fixture VAT rate is 12.5%.
"""

from datetime import date
from decimal import Decimal

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
from munisense.domain.money import Money, RateUnit
from munisense.domain.tariffs import (
    Component,
    DayType,
    TariffVersion,
    TouCalendar,
    TouPeriod,
    TouRate,
    UndefinedPeriodError,
)
from support.builders import (
    FIXTURE_TOU_CENTS,
    cited_rate,
    fixture_calendar,
    fixture_flat,
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
    millionths): peak 31 kWh -> 16.999997 (low) and 14.000003 (high)."""
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    version = tou_version(start=date(2026, 4, 1))
    bill = calculate_period([version], period, used("31", "62", "93"), VAT)
    low, june = bill.parts
    assert low.period.end == june.period.start == date(2026, 6, 1)
    peak_low = next(
        line
        for line in low.lines
        if "peak kWh" in line.description and "off" not in line.description
    )
    assert peak_low.description == "low demand season: peak kWh"
    assert peak_low.quantity == Decimal("16.999997")
    assert sum(p.consumption_kwh for p in bill.parts) == Decimal(186)
    assert bill.consumption_kwh == Decimal(186)


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
