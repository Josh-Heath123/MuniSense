"""P1-12: seasonal energy.

Fixture tariffs only (invented values, fixture VAT 12.5%; lines, VAT on the subtotal and the
total to cents, half up). The fixture seasons follow the shape of a South African schedule:
a high-demand season from June to August and a low-demand season from September to May.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    NonMonthlyPeriodError,
    PeriodCrossesSeasonError,
    PeriodTotal,
    SourceRole,
    calculate_bill,
)
from munisense.domain.citations import ProvidedBy, StatusKind, UserProvided
from munisense.domain.money import Money, RateUnit
from munisense.domain.tariffs import Season, SeasonalEnergy, SeasonDates, TariffVersion
from support.builders import (
    cited_label,
    fixture_fixed,
    fixture_free_basic,
    fixture_season,
    fixture_seasonal,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
BASIC = fixture_fixed("100.00")
DAILY = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
HIGH_FLAT = fixture_season("high", (6, 1), (8, 31), (None, "300.00"))
LOW_FLAT = fixture_season("low", (9, 1), (5, 31), (None, "200.00"))
LOW_BLOCKS = fixture_season("low", (9, 1), (5, 31), ("50", "150.00"), (None, "200.00"))
SEASONAL = fixture_seasonal(HIGH_FLAT, LOW_BLOCKS)
FLAT_SEASONS = fixture_seasonal(HIGH_FLAT, LOW_FLAT)


def period(start: date, end: date) -> BillingPeriod:
    return BillingPeriod(start=start, end=end)


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


def kwh(value: str) -> PeriodTotal:
    return PeriodTotal(kwh=Decimal(value))


# ------------------------------------------------------------------------ pricing


def test_a_high_season_month_uses_the_high_season_rate() -> None:
    # July: 100 kWh x 300c = 300.00; basic 100.00; subtotal 400.00; VAT 50.00; total 450.00
    bill = calculate_bill(
        fixture_version(BASIC, SEASONAL),
        period(date(2026, 7, 1), date(2026, 8, 1)),
        kwh("100"),
        VAT,
    )
    energy = bill.lines[1]
    assert energy.description == "high season: all kWh"
    assert energy.amount == rand("300.00")
    assert bill.total == rand("450.00")


def test_a_low_season_month_uses_the_low_season_blocks() -> None:
    # January: 50 kWh x 150c = 75.00; 70 kWh x 200c = 140.00; basic 100.00
    # subtotal 315.00; VAT 12.5% = 39.375 -> 39.38; total 354.38
    bill = calculate_bill(
        fixture_version(BASIC, SEASONAL),
        period(date(2027, 1, 1), date(2027, 2, 1)),
        kwh("120"),
        VAT,
    )
    assert [(line.description, line.amount) for line in bill.lines[1:]] == [
        ("low season: block 1: 0 to 50 kWh", rand("75.00")),
        ("low season: block 2: above 50 kWh", rand("140.00")),
    ]
    assert bill.total == rand("354.38")


def test_every_seasonal_line_cites_the_season_it_used() -> None:
    bill = calculate_bill(
        fixture_version(BASIC, SEASONAL),
        period(date(2027, 1, 1), date(2027, 2, 1)),
        kwh("120"),
        VAT,
    )
    for line in bill.lines[1:]:
        seasons = [s.citation.printed_text for s in line.sources if s.role is SourceRole.SEASON]
        assert seasons == ["low dates"]


@pytest.mark.parametrize(
    ("start", "end", "amount"),
    [
        # The period's exclusive end is the next season's first day: still one season.
        (date(2026, 8, 1), date(2026, 9, 1), "300.00"),  # August: high, 100 kWh x 300c
        (date(2027, 5, 1), date(2027, 6, 1), "200.00"),  # May: low, 100 kWh x 200c
    ],
)
def test_the_last_month_of_a_season_is_priced_in_that_season(
    start: date, end: date, amount: str
) -> None:
    bill = calculate_bill(fixture_version(BASIC, FLAT_SEASONS), period(start, end), kwh("100"), VAT)
    assert bill.lines[1].amount == rand(amount)


def test_a_weaker_season_label_weakens_the_bill() -> None:
    weak = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    base = fixture_season("high", (6, 1), (8, 31), (None, "300.00"))
    high = Season(
        name=base.name,
        label=cited_label("high season", weak),
        dates=base.dates,
        blocks=base.blocks,
    )
    tariff = fixture_version(BASIC, fixture_seasonal(high, LOW_FLAT))
    july = calculate_bill(tariff, period(date(2026, 7, 1), date(2026, 8, 1)), kwh("10"), VAT)
    january = calculate_bill(tariff, period(date(2027, 1, 1), date(2027, 2, 1)), kwh("10"), VAT)
    assert july.status is StatusKind.USER_PROVIDED
    assert january.status is StatusKind.ESTIMATED  # the weak label is not used in January
    roles = [s.role for s in july.lines[1].sources]
    assert SourceRole.SEASON in roles
    assert SourceRole.SEASON_LABEL in roles


def test_a_part_month_inside_one_flat_season_is_priced() -> None:
    # 5 June to 20 July (45 days, all high season): 45 x R1.00 = 45.00; 10 kWh x 300c = 30.00
    # subtotal 75.00; VAT 9.375 -> 9.38; total 84.38
    bill = calculate_bill(
        fixture_version(DAILY, FLAT_SEASONS, end=None),
        period(date(2027, 6, 5), date(2027, 7, 20)),
        kwh("10"),
        VAT,
    )
    assert bill.lines[0].quantity == Decimal(45)
    assert bill.total == rand("84.38")


def test_a_season_that_wraps_past_the_new_year_covers_december_to_january() -> None:
    # 15 December to 15 January is all low season: 10 kWh x 200c = 20.00
    bill = calculate_bill(
        fixture_version(DAILY, FLAT_SEASONS),
        period(date(2026, 12, 15), date(2027, 1, 15)),
        kwh("10"),
        VAT,
    )
    assert bill.lines[1].amount == rand("20.00")


def test_a_period_across_a_season_boundary_is_refused() -> None:
    with pytest.raises(PeriodCrossesSeasonError):
        calculate_bill(
            fixture_version(DAILY, FLAT_SEASONS),
            period(date(2026, 8, 15), date(2026, 9, 15)),
            kwh("10"),
            VAT,
        )


def test_season_thresholds_refuse_a_part_month() -> None:
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(
            fixture_version(DAILY, SEASONAL),
            period(date(2027, 1, 5), date(2027, 1, 20)),
            kwh("10"),
            VAT,
        )


def test_one_season_for_the_whole_year_applies_to_any_period() -> None:
    year = fixture_seasonal(fixture_season("all", (1, 1), (12, 31), (None, "100.00")))
    long = period(date(2026, 7, 1), date(2030, 7, 1))
    bill = calculate_bill(fixture_version(DAILY, year, end=None), long, kwh("1"), VAT)
    assert bill.lines[1].amount == rand("1.00")


def test_a_free_allocation_can_take_its_kwh_from_seasonal_energy() -> None:
    # January, 120 kWh, 60 free: credits 50 x 150c = -75.00 and 10 x 200c = -20.00
    # subtotal 100.00 + 75.00 + 140.00 - 95.00 = 220.00; VAT 27.50; total 247.50
    tariff = fixture_version(BASIC, SEASONAL, fixture_free_basic("60"))
    bill = calculate_bill(
        tariff,
        period(date(2027, 1, 1), date(2027, 2, 1)),
        kwh("120"),
        VAT,
        free_basic_eligible=True,
    )
    credits = [line for line in bill.lines if line.component == "free_basic"]
    assert [line.amount for line in credits] == [rand("-75.00"), rand("-20.00")]
    for line in credits:
        seasons = [s.citation.printed_text for s in line.sources if s.role is SourceRole.SEASON]
        assert seasons == ["low dates"]
    assert bill.total == rand("247.50")


# --------------------------------------------------------------- the calendar


def test_the_seasons_are_found_for_single_days() -> None:
    assert SEASONAL.season_for(date(2026, 8, 31), date(2026, 8, 31)) is HIGH_FLAT
    assert SEASONAL.season_for(date(2026, 9, 1), date(2026, 9, 1)) is LOW_BLOCKS
    assert SEASONAL.season_for(date(2028, 2, 29), date(2028, 2, 29)) is LOW_BLOCKS
    assert SEASONAL.season_for(date(2026, 5, 31), date(2026, 6, 1)) is None
    assert SEASONAL.season_for(date(2026, 9, 1), date(2027, 9, 2)) is None  # over a year


@pytest.mark.parametrize(
    ("seasons", "problem"),
    [
        (
            (HIGH_FLAT, fixture_season("low", (9, 1), (4, 30), (None, "1"))),
            "01 May has no season",
        ),
        (
            (HIGH_FLAT, fixture_season("low", (8, 1), (5, 31), (None, "1"))),
            "01 August has more than one season",
        ),
        (
            (
                fixture_season("a", (1, 1), (2, 28), (None, "1")),
                fixture_season("b", (3, 1), (12, 31), (None, "1")),
            ),
            "29 February has no season",
        ),
    ],
    ids=["gap", "overlap", "leap day"],
)
def test_the_seasons_must_cover_every_day_exactly_once(
    seasons: tuple[Season, ...], problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        fixture_seasonal(*seasons)


def test_season_names_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique"):
        fixture_seasonal(
            fixture_season("same", (6, 1), (8, 31), (None, "1")),
            fixture_season("same", (9, 1), (5, 31), (None, "1")),
        )


@pytest.mark.parametrize(("month", "day"), [(4, 31), (2, 30), (13, 1), (0, 1)])
def test_a_season_date_must_be_a_real_day(month: int, day: int) -> None:
    with pytest.raises(ValidationError):
        SeasonDates(start_month=month, start_day=day, end_month=12, end_day=31)


def test_a_season_needs_ordered_blocks_with_an_open_last_block() -> None:
    with pytest.raises(ValidationError):
        fixture_season("bad", (1, 1), (12, 31), ("50", "1"))


def test_a_seasonal_tariff_survives_a_json_round_trip() -> None:
    tariff = fixture_version(BASIC, SEASONAL)
    again = TariffVersion.model_validate_json(tariff.model_dump_json())
    assert again == tariff
    assert isinstance(again.components[1], SeasonalEnergy)
