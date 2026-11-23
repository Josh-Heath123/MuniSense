"""The quantity charge: a monthly charge per kVA of a customer-given quantity (P4-9).

The Miniflex example uses one printed rate from Eskom's 2026/27 tariff book (PDF page 19,
printed page 20): the network capacity charge for a supply within 300 km at under 500 V,
R54.22 per kVA per month, charged on the monthly utilised capacity. Here it is a fixture
value, `estimated`; nothing is published. Other values are made up. VAT 12.5% (fixture).
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    MissingQuantityError,
    MonthSoFar,
    NonMonthlyPeriodError,
    PeriodTotal,
    PrepaidNotSupportedError,
    calculate_bill,
    calculate_period,
    calculate_purchase,
)
from munisense.domain.billing.errors import PeriodCrossesSeasonError
from munisense.domain.citations import Cited
from munisense.domain.money import Money
from munisense.domain.tariffs import (
    CalendarSeason,
    Component,
    DayType,
    Quantity,
    SeasonDates,
    TariffVersion,
    TouCalendar,
    TouPeriod,
)
from support.builders import (
    FIXTURE_STATUS,
    fixture_calendar,
    fixture_citation,
    fixture_flat,
    fixture_quantity_charge,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
CALENDAR = fixture_calendar()
JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
JANUARY = BillingPeriod(start=date(2027, 1, 1), end=date(2027, 2, 1))
NOTHING = PeriodTotal(kwh=Decimal(0))
UTILISED = Quantity.UTILISED_CAPACITY_KVA
MINIFLEX = fixture_quantity_charge("54.22")


def version(*components: Component, calendar: bool = False) -> TariffVersion:
    return fixture_version(
        fixture_flat("100"),
        *(components or (MINIFLEX,)),
        tou_calendar=CALENDAR if calendar else None,
    )


def test_the_miniflex_network_capacity_line_by_hand() -> None:
    """100 kVA utilised capacity x R54.22 per kVA per month = R5,422.00 for July."""
    bill = calculate_bill(version(), JULY, NOTHING, VAT, quantities={UTILISED: Decimal(100)})
    line = next(line for line in bill.lines if line.component == "network_capacity")
    assert line.description == "utilised capacity 100 kVA, 1 month"
    assert (line.quantity, line.amount.rand) == (Decimal(100), Decimal("5422.00"))
    assert bill.vat.rand == Decimal("677.75")  # 12.5% of R5,422.00


def test_a_part_month_is_pro_rated_like_any_monthly_value() -> None:
    """15 July to 1 August: 17/31 = 0.548387 of a month (fixture millionths):
    100 kVA x 0.548387 = 54.8387 kVA-months x R54.22 = R2,973.354... -> R2,973.35."""
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 1))
    bill = calculate_period([version()], period, NOTHING, VAT, quantities={UTILISED: Decimal(100)})
    line = next(line for line in bill.parts[0].lines if line.component == "network_capacity")
    assert line.quantity == Decimal("54.8387")
    assert line.amount.rand == Decimal("2973.35")
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(version(), period, NOTHING, VAT, quantities={UTILISED: Decimal(100)})


def test_a_missing_quantity_is_refused() -> None:
    with pytest.raises(MissingQuantityError, match="give the customer's utilised capacity"):
        calculate_bill(version(), JULY, NOTHING, VAT)


@pytest.mark.parametrize("value", [Decimal(-1), Decimal("NaN"), 100.0])
def test_a_quantity_that_is_negative_or_not_an_exact_decimal_is_refused(value: object) -> None:
    with pytest.raises(MissingQuantityError, match="non-negative exact decimal"):
        calculate_bill(version(), JULY, NOTHING, VAT, quantities={UTILISED: value})  # type: ignore[dict-item]


def test_a_quantity_no_charge_uses_is_refused() -> None:
    """It would be silently ignored."""
    with pytest.raises(MissingQuantityError, match="no charge on the measured maximum demand"):
        calculate_bill(
            version(),
            JULY,
            NOTHING,
            VAT,
            quantities={UTILISED: Decimal(1), Quantity.MEASURED_MAXIMUM_DEMAND_KVA: Decimal(1)},
        )


def test_a_quantity_charge_is_priced_per_kva_per_month_only() -> None:
    with pytest.raises(ValidationError, match="a quantity charge must be priced per R/kVA/month"):
        fixture_quantity_charge().model_validate(
            {**fixture_quantity_charge().model_dump(), "rate": fixture_flat("1").rate.model_dump()}
        )


# ------------------------------------------------------------------- limited to seasons


HIGH_ONLY = fixture_quantity_charge("20.00", seasons=("high",), name="high_season_demand")


def test_a_charge_limited_to_a_season_applies_only_in_it() -> None:
    with_calendar = version(HIGH_ONLY, calendar=True)
    july = calculate_bill(with_calendar, JULY, NOTHING, VAT, quantities={UTILISED: Decimal(10)})
    january = calculate_bill(
        with_calendar, JANUARY, NOTHING, VAT, quantities={UTILISED: Decimal(10)}
    )
    assert {line.component for line in july.lines} == {"high_season_demand"}
    assert july.subtotal.rand == Decimal("200.00")  # 10 kVA x R20.00
    assert january.subtotal.rand == 0


def test_a_season_limited_charge_needs_the_calendar_but_not_kwh_per_period() -> None:
    """It needs the calendar for its seasons; a period total still prices the version."""
    assert HIGH_ONLY.needs_calendar
    assert not MINIFLEX.needs_calendar
    with pytest.raises(ValidationError, match="need a time-of-use calendar"):
        version(HIGH_ONLY)
    bill = calculate_bill(
        version(HIGH_ONLY, calendar=True),
        JULY,
        PeriodTotal(kwh=Decimal(10)),
        VAT,
        quantities={UTILISED: Decimal(1)},
    )
    assert bill.subtotal.rand == Decimal("30.00")  # 10 kWh x R1.00 + 1 kVA x R20.00


def test_a_season_or_period_the_calendar_lacks_is_refused() -> None:
    with pytest.raises(ValidationError, match="names the season 'winter'"):
        version(fixture_quantity_charge(seasons=("winter",)), calendar=True)
    day = ((7 * 60, TouPeriod.OFF_PEAK), (9 * 60, TouPeriod.PEAK), (24 * 60, TouPeriod.OFF_PEAK))
    hours: dict[DayType, tuple[tuple[int, TouPeriod], ...]] = dict.fromkeys(DayType, day)
    no_standard = fixture_calendar(hours, hours)
    with pytest.raises(ValidationError, match="names the period standard"):
        fixture_version(
            fixture_flat("100"),
            fixture_quantity_charge(periods=(TouPeriod.STANDARD,)),
            tou_calendar=no_standard,
        )


def test_the_measured_periods_are_shown_on_the_line() -> None:
    peak_and_standard = fixture_quantity_charge(
        "10.00",
        quantity=Quantity.MEASURED_MAXIMUM_DEMAND_KVA,
        periods=(TouPeriod.PEAK, TouPeriod.STANDARD),
        name="demand",
    )
    bill = calculate_bill(
        version(peak_and_standard, calendar=True),
        JULY,
        NOTHING,
        VAT,
        quantities={Quantity.MEASURED_MAXIMUM_DEMAND_KVA: Decimal(3)},
    )
    line = next(line for line in bill.lines if line.component == "demand")
    assert (
        line.description == "measured maximum demand 3 kVA, in peak and standard periods, 1 month"
    )


def test_a_bill_across_the_season_change_is_split_and_charged_only_in_high_season() -> None:
    """15 May to 15 June: the part from 1 June (14 of June's 30 days, factor 0.466667)
    is high season: 10 kVA x 0.466667 x R20.00 = R93.3334 -> R93.33."""
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    versioned = fixture_version(
        fixture_flat("100"), HIGH_ONLY, tou_calendar=CALENDAR, start=date(2026, 4, 1)
    )
    with pytest.raises(NonMonthlyPeriodError):  # a monthly charge needs one calendar month
        calculate_bill(versioned, period, NOTHING, VAT, quantities={UTILISED: Decimal(10)})
    bill = calculate_period([versioned], period, NOTHING, VAT, quantities={UTILISED: Decimal(10)})
    charged = [
        line for part in bill.parts for line in part.lines if line.component == "high_season_demand"
    ]
    assert [line.amount.rand for line in charged] == [Decimal("93.33")]


def test_prepaid_purchases_on_a_tariff_with_a_quantity_charge_are_refused() -> None:
    with pytest.raises(PrepaidNotSupportedError, match="demand or capacity charge"):
        calculate_purchase(
            version(),
            date(2026, 7, 1),
            Money(rand=Decimal(100)),
            MonthSoFar(purchases=0, kwh=Decimal(0)),
            VAT,
        )


def test_a_month_across_a_mid_month_season_change_is_split() -> None:
    """A made-up calendar whose high season starts on 15 June: June crosses the change,
    so `calculate_bill` refuses it and `calculate_period` charges only the high part
    (16 of June's 30 days, factor 0.533333: 10 kVA x 0.533333 x R20.00 = R106.67)."""
    high = SeasonDates(start_month=6, start_day=15, end_month=9, end_day=14)
    low = SeasonDates(start_month=9, start_day=15, end_month=6, end_day=14)
    seasons = tuple(
        CalendarSeason(
            name=name,
            label=season.label,
            dates=Cited[SeasonDates](
                value=dates, citation=fixture_citation(f"{name} dates"), status=FIXTURE_STATUS
            ),
        )
        for name, dates, season in (
            ("high", high, CALENDAR.seasons[0]),
            ("low", low, CALENDAR.seasons[1]),
        )
    )
    mid_month = TouCalendar(
        seasons=seasons, schedules=CALENDAR.schedules, holidays=CALENDAR.holidays
    )
    versioned = fixture_version(
        fixture_flat("100"), HIGH_ONLY, tou_calendar=mid_month, start=date(2026, 4, 1)
    )
    june = BillingPeriod(start=date(2026, 6, 1), end=date(2026, 7, 1))
    with pytest.raises(PeriodCrossesSeasonError, match="season boundary"):
        calculate_bill(versioned, june, NOTHING, VAT, quantities={UTILISED: Decimal(10)})
    bill = calculate_period([versioned], june, NOTHING, VAT, quantities={UTILISED: Decimal(10)})
    charged = [
        line.amount.rand
        for part in bill.parts
        for line in part.lines
        if line.component == "high_season_demand"
    ]
    assert charged == [Decimal("106.67")]


def test_a_season_or_period_named_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="each season and period once"):
        fixture_quantity_charge(seasons=("high", "high"))
    with pytest.raises(ValidationError, match="each season and period once"):
        fixture_quantity_charge(periods=(TouPeriod.PEAK, TouPeriod.PEAK))
