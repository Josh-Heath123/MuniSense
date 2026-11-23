"""The quantity charge: a monthly charge per kVA of a customer-given quantity (P4-9).

The Miniflex example uses one printed rate from Eskom's 2026/27 tariff book (PDF page 19,
printed page 20): the network capacity charge for a supply within 300 km at under 500 V,
R54.22 per kVA per month in the Miniflex Non-local Authority table, charged on the annual
utilised capacity (the higher of the NMD and the maximum demand over a rolling 12 months,
book PDF page 18 and definitions). Here it is cited to that page, `estimated`; nothing is
published. Other values are made up. VAT 12.5% (fixture).
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    CustomerQuantities,
    InvalidQuantityError,
    MonthSoFar,
    NonMonthlyPeriodError,
    PeriodTotal,
    PrepaidNotSupportedError,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    calculate_bill,
    calculate_period,
    calculate_purchase,
)
from munisense.domain.billing.errors import PeriodCrossesSeasonError
from munisense.domain.billing.result import SourceRole
from munisense.domain.citations import Citation, Cited, Estimated, StatusKind
from munisense.domain.money import Money, Rate, RateUnit
from munisense.domain.tariffs import (
    CalendarSeason,
    Component,
    DayType,
    Quantity,
    QuantityCharge,
    SeasonDates,
    TariffVersion,
    TouCalendar,
    TouPeriod,
)
from support.builders import (
    FIXTURE_STATUS,
    cited_label,
    cited_vat,
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
UTILISED = Quantity.ANNUAL_UTILISED_CAPACITY_KVA
BOOK = "eef82b077d7df4dd7b157ce757e2e56368170cec3bb69614fd81042451a1be84"
MINIFLEX = QuantityCharge(
    schema_version=1,
    kind="quantity_charge",
    name="network_capacity",
    label=cited_label("Network capacity charge"),
    vat=cited_vat(),
    quantity=Quantity.ANNUAL_UTILISED_CAPACITY_KVA,
    rate=Cited[Rate](
        value=Rate(value=Decimal("54.22"), unit=RateUnit.RAND_PER_KVA_PER_MONTH),
        citation=Citation(
            document_sha256=BOOK,
            page=19,
            locator="Miniflex - Non-local Authority; <= 300km, < 500V; network capacity charge",
            printed_text="R54.22",
        ),
        status=Estimated(reason="reproduced by hand in a test; not published (P4-9)"),
    ),
)


def capacity(kva: int) -> CustomerQuantities:
    return CustomerQuantities(annual_utilised_capacity_kva=Decimal(kva))


def version(*components: Component, calendar: bool = False) -> TariffVersion:
    return fixture_version(
        fixture_flat("100"),
        *(components or (MINIFLEX,)),
        tou_calendar=CALENDAR if calendar else None,
    )


def test_the_miniflex_network_capacity_line_by_hand() -> None:
    """100 kVA annual utilised capacity x R54.22 per kVA per month = R5,422.00 for July."""
    bill = calculate_bill(version(), JULY, NOTHING, VAT, quantities=capacity(100))
    line = next(line for line in bill.lines if line.component == "network_capacity")
    assert line.description == "annual utilised capacity 100 kVA, 1 month"
    assert (line.quantity, line.amount.rand) == (Decimal(100), Decimal("5422.00"))
    assert line.status is StatusKind.ESTIMATED
    rate_source = next(s for s in line.sources if s.role is SourceRole.RATE)
    assert (rate_source.citation.page, rate_source.citation.printed_text) == (19, "R54.22")
    assert bill.vat.rand == Decimal("677.75")  # 12.5% of R5,422.00


def test_a_part_month_is_pro_rated_like_any_monthly_value() -> None:
    """15 July to 1 August: 17/31 = 0.548387 of a month (fixture millionths):
    100 kVA x 0.548387 = 54.8387 kVA-months x R54.22 = R2,973.354... -> R2,973.35."""
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 1))
    bill = calculate_period([version()], period, NOTHING, VAT, quantities=capacity(100))
    line = next(line for line in bill.parts[0].lines if line.component == "network_capacity")
    assert line.quantity == Decimal("54.8387")
    assert line.amount.rand == Decimal("2973.35")
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(version(), period, NOTHING, VAT, quantities=capacity(100))


def test_a_missing_quantity_is_refused() -> None:
    with pytest.raises(InvalidQuantityError, match="give the customer's annual utilised capacity"):
        calculate_bill(version(), JULY, NOTHING, VAT)
    with pytest.raises(InvalidQuantityError, match="give the customer's annual utilised capacity"):
        calculate_period([version()], JULY, NOTHING, VAT)


def test_a_zero_quantity_is_charged_nothing() -> None:
    bill = calculate_bill(version(), JULY, NOTHING, VAT, quantities=capacity(0))
    line = next(line for line in bill.lines if line.component == "network_capacity")
    assert line.amount.rand == 0


@pytest.mark.parametrize(
    ("text", "planted"),
    [
        ('{"annual_utilised_capacity_kva": "-1"}', "-1"),
        ('{"annual_utilised_capacity_kva": 100.5}', "100.5"),
        ('{"annual_utilised_capacity_kva": "NaN"}', "NaN"),
        ('{"annual_utilised_capacity_kva": "1234567890123456"}', "1234567890123456"),
        ('{"utilised_capacity_kva": "7"}', "7"),  # an unknown name
    ],
)
def test_quantities_are_strict_and_exact_and_hide_their_values(text: str, planted: str) -> None:
    """Values are never repeated in the message. An unknown name is refused; like every
    model, its message names the field path, so P5 reads this input through a parser
    that shows fixed text only (as P4-4 did for consumption)."""
    with pytest.raises(ValidationError) as caught:
        CustomerQuantities.model_validate_json(text)
    assert f"input_value='{planted}'" not in str(caught.value)
    assert f"input_value={planted}" not in str(caught.value)


def test_a_negative_zero_quantity_becomes_zero() -> None:
    assert (
        not CustomerQuantities(annual_utilised_capacity_kva=Decimal("-0"))
        .given()[UTILISED]
        .is_signed()
    )


def test_a_quantity_no_charge_uses_is_refused() -> None:
    """It would be silently ignored."""
    with pytest.raises(InvalidQuantityError, match="no charge on the measured maximum demand"):
        calculate_bill(
            version(),
            JULY,
            NOTHING,
            VAT,
            quantities=CustomerQuantities(
                annual_utilised_capacity_kva=Decimal(1), measured_maximum_demand_kva=Decimal(1)
            ),
        )


def test_one_quantity_is_not_charged_again_for_another_month() -> None:
    """A demand or a capacity is the customer's figure for one month; July and August need
    two bills."""
    both = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 9, 1))
    with pytest.raises(InvalidQuantityError, match="give one bill per calendar month"):
        calculate_period([version()], both, NOTHING, VAT, quantities=capacity(100))


def test_a_quantity_charge_is_priced_per_kva_per_month_only() -> None:
    with pytest.raises(ValidationError, match="a quantity charge must be priced per R/kVA/month"):
        fixture_quantity_charge().model_validate(
            {**fixture_quantity_charge().model_dump(), "rate": fixture_flat("1").rate.model_dump()}
        )


# ------------------------------------------------------------------- limited to seasons


HIGH_ONLY = fixture_quantity_charge("20.00", seasons=("high",), name="high_season_demand")


def test_a_charge_limited_to_a_season_applies_only_in_it() -> None:
    with_calendar = version(HIGH_ONLY, calendar=True)
    july = calculate_bill(with_calendar, JULY, NOTHING, VAT, quantities=capacity(10))
    january = calculate_bill(with_calendar, JANUARY, NOTHING, VAT, quantities=capacity(10))
    (line,) = july.lines
    assert line.description == "high demand season: annual utilised capacity 10 kVA, 1 month"
    roles = {source.role for source in line.sources}
    assert {SourceRole.SEASON, SourceRole.SEASON_LABEL} <= roles
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
        quantities=capacity(1),
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
        quantities=CustomerQuantities(measured_maximum_demand_kva=Decimal(3)),
    )
    line = next(line for line in bill.lines if line.component == "demand")
    assert (
        line.description == "measured maximum demand 3 kVA, in peak and standard periods, 1 month"
    )


def test_a_bill_across_two_months_and_a_season_change_is_refused() -> None:
    """15 May to 15 June needs two months' quantities, so it is refused (a season change
    inside one month is split and priced: see the mid-month test below)."""
    period = BillingPeriod(start=date(2026, 5, 15), end=date(2026, 6, 15))
    versioned = fixture_version(
        fixture_flat("100"), HIGH_ONLY, tou_calendar=CALENDAR, start=date(2026, 4, 1)
    )
    with pytest.raises(NonMonthlyPeriodError):  # a monthly charge needs one calendar month
        calculate_bill(versioned, period, NOTHING, VAT, quantities=capacity(10))
    with pytest.raises(InvalidQuantityError, match="one bill per calendar month"):
        calculate_period([versioned], period, NOTHING, VAT, quantities=capacity(10))


def test_kwh_per_period_cannot_price_a_tariff_whose_only_calendar_use_is_a_season() -> None:
    profile = TimeOfUseBuckets(
        used_kwh={
            TouPeriod.PEAK: Decimal(1),
            TouPeriod.STANDARD: Decimal(1),
            TouPeriod.OFF_PEAK: Decimal(1),
        }
    )
    with pytest.raises(UnsupportedConsumptionError, match="price only a tariff priced by time"):
        calculate_bill(
            version(HIGH_ONLY, calendar=True), JULY, profile, VAT, quantities=capacity(1)
        )


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
        calculate_bill(versioned, june, NOTHING, VAT, quantities=capacity(10))
    bill = calculate_period([versioned], june, NOTHING, VAT, quantities=capacity(10))
    charged = [
        line.amount.rand
        for part in bill.parts
        for line in part.lines
        if line.component == "high_season_demand"
    ]
    assert charged == [Decimal("106.67")]


def test_a_charge_with_measured_periods_only_does_not_cut_a_month_at_a_season() -> None:
    """`periods` only labels the line; a season change inside the month cuts nothing, so
    `calculate_period` agrees with `calculate_bill` (P4-9 review)."""
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
    demand = fixture_quantity_charge("10.00", periods=(TouPeriod.PEAK,), name="demand")
    versioned = fixture_version(
        fixture_flat("100"), demand, tou_calendar=mid_month, start=date(2026, 4, 1)
    )
    june = BillingPeriod(start=date(2026, 6, 1), end=date(2026, 7, 1))
    single = calculate_bill(versioned, june, NOTHING, VAT, quantities=capacity(10))
    split = calculate_period([versioned], june, NOTHING, VAT, quantities=capacity(10))
    assert len(split.parts) == 1
    assert split.total == single.total


def test_a_season_or_period_named_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="each season and period once"):
        fixture_quantity_charge(seasons=("high", "high"))
    with pytest.raises(ValidationError, match="each season and period once"):
        fixture_quantity_charge(periods=(TouPeriod.PEAK, TouPeriod.PEAK))


def test_a_mid_month_tariff_change_that_drops_the_charge_is_priced() -> None:
    """Version A (to 16 July) has the capacity charge; version B (from 16 July) has none.
    The quantity is checked once across both; B's part is not refused for it.
    A's part: 100 kVA x 15/31 (0.483871) x R54.22 = R2,623.548... -> R2,623.55."""
    a = fixture_version(fixture_flat("100"), MINIFLEX, end=date(2026, 7, 16))
    b = fixture_version(fixture_flat("100"), start=date(2026, 7, 16), end=None)
    bill = calculate_period([a, b], JULY, NOTHING, VAT, quantities=capacity(100))
    charged = [
        line.amount.rand
        for part in bill.parts
        for line in part.lines
        if line.component == "network_capacity"
    ]
    assert charged == [Decimal("2623.55")]
    with pytest.raises(InvalidQuantityError, match="no charge on the measured maximum demand"):
        calculate_period(
            [a, b],
            JULY,
            NOTHING,
            VAT,
            quantities=CustomerQuantities(
                annual_utilised_capacity_kva=Decimal(100), measured_maximum_demand_kva=Decimal(1)
            ),
        )
