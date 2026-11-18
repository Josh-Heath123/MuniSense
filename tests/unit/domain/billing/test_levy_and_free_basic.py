"""P1-11: levies and the free basic allocation.

Fixture tariffs only (invented values, fixture VAT 12.5%). Unless a test says otherwise the
policy rounds lines, VAT (once on the subtotal) and the total to cents, half up.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    FreeBasicEligibilityRequiredError,
    FreeBasicNotOfferedError,
    NonMonthlyPeriodError,
    PeriodTotal,
    SourceRole,
    WarningCode,
    calculate_bill,
)
from munisense.domain.citations import StatusKind, UserProvided
from munisense.domain.citations.model import ProvidedBy
from munisense.domain.money import Money, Quantisation, RateUnit, RoundingMode, VatApplication
from munisense.domain.tariffs import FreeBasicAllocation, Levy, TariffVersion, VatTreatment
from support.builders import (
    cited_decimal,
    fixture_blocks,
    fixture_fixed,
    fixture_flat,
    fixture_free_basic,
    fixture_levy,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
PART_MONTH = BillingPeriod(start=date(2026, 7, 10), end=date(2026, 8, 12))
VAT = fixture_vat_table()
BASIC = fixture_fixed("100.00")
FLAT = fixture_flat("180.00")
BLOCKS = fixture_blocks(("50", "152.37"), ("350", "201.11"), (None, "257.89"))


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


def kwh(value: str) -> PeriodTotal:
    return PeriodTotal(kwh=Decimal(value))


# -------------------------------------------------------------------------- levies


def test_a_levy_per_kwh_is_charged_on_every_kwh() -> None:
    # basic 100.00; energy 100 kWh x 180c = 180.00; levy 100 kWh x 2.5c = 2.50
    # subtotal 282.50; VAT 12.5% = 35.3125 -> 35.31; total 317.81
    tariff = fixture_version(BASIC, FLAT, fixture_levy("2.5"))
    bill = calculate_bill(tariff, JULY, kwh("100"), VAT)
    assert [(line.component, line.amount) for line in bill.lines] == [
        ("basic", rand("100.00")),
        ("energy", rand("180.00")),
        ("levy", rand("2.50")),
    ]
    assert bill.vat == rand("35.31")
    assert bill.total == rand("317.81")


def test_a_levy_per_kwh_gives_no_line_at_zero_use() -> None:
    bill = calculate_bill(fixture_version(BASIC, FLAT, fixture_levy("2.5")), JULY, kwh("0"), VAT)
    assert [line.component for line in bill.lines] == ["basic"]


def test_a_daily_levy_counts_the_days_and_allows_any_period() -> None:
    # 33 days (10 July to 12 August) x R0.50 = 16.50; energy 10 kWh x 180c = 18.00
    # subtotal 34.50; VAT 12.5% = 4.3125 -> 4.31; total 38.81
    tariff = fixture_version(FLAT, fixture_levy("0.50", RateUnit.RAND_PER_DAY))
    bill = calculate_bill(tariff, PART_MONTH, kwh("10"), VAT)
    assert bill.lines[1].quantity == Decimal(33)
    assert bill.lines[1].amount == rand("16.50")
    assert bill.total == rand("38.81")


def test_a_monthly_levy_refuses_a_part_month() -> None:
    tariff = fixture_version(FLAT, fixture_levy("12.00", RateUnit.RAND_PER_MONTH))
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(tariff, PART_MONTH, kwh("10"), VAT)


def test_a_zero_rated_levy_stays_out_of_the_vat_base() -> None:
    # basic 100.00 (standard); levy R20.00/month (zero-rated); subtotal 120.00
    # VAT 12.5% of 100.00 = 12.50; total 132.50
    levy = fixture_levy("20.00", RateUnit.RAND_PER_MONTH, vat=VatTreatment.ZERO_RATED)
    bill = calculate_bill(fixture_version(BASIC, levy), JULY, kwh("0"), VAT)
    assert bill.subtotal == rand("120.00")
    assert bill.vat == rand("12.50")
    assert bill.total == rand("132.50")


@pytest.mark.parametrize("unit", list(RateUnit))
def test_a_levy_accepts_every_rate_unit(unit: RateUnit) -> None:
    assert fixture_levy("1.00", unit).rate.value.unit is unit


@pytest.mark.parametrize("value", ["-1.00", "-0"])
def test_a_levy_must_not_be_negative(value: str) -> None:
    with pytest.raises(ValidationError):
        fixture_levy(value)


# ------------------------------------------------------------ free basic allocation


def test_use_within_the_allocation_costs_only_the_fixed_charge() -> None:
    # energy 30 kWh x 180c = 54.00; free 30 kWh credited -54.00
    # subtotal 100.00; VAT 12.50; total 112.50
    tariff = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    bill = calculate_bill(tariff, JULY, kwh("30"), VAT, free_basic_eligible=True)
    assert [(line.component, line.amount) for line in bill.lines] == [
        ("basic", rand("100.00")),
        ("energy", rand("54.00")),
        ("free_basic", rand("-54.00")),
    ]
    assert bill.total == rand("112.50")


def test_use_above_a_flat_allocation_pays_for_the_rest() -> None:
    # energy 120 kWh x 180c = 216.00; free 50 kWh x 180c credited -90.00
    # subtotal 100.00 + 216.00 - 90.00 = 226.00; VAT 28.25; total 254.25
    tariff = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    bill = calculate_bill(tariff, JULY, kwh("120"), VAT, free_basic_eligible=True)
    assert bill.lines[2].quantity == Decimal(50)
    assert bill.lines[2].amount == rand("-90.00")
    assert bill.subtotal == rand("226.00")
    assert bill.total == rand("254.25")


def test_an_allocation_spanning_two_blocks_credits_each_block_at_its_rate() -> None:
    # 412.3 kWh, blocks 0-50 at 152.37c, 50-350 at 201.11c, above at 257.89c; 60 kWh free
    #   basic 213.45; block 1 76.185 -> 76.19; block 2 603.33; block 3 160.66547 -> 160.67
    #   free block 1: 50 kWh -> -76.19; free block 2: 10 kWh x 201.11c = 20.111 -> -20.11
    #   subtotal 957.34; VAT 12.5% = 119.6675 -> 119.67; total 1077.01
    tariff = fixture_version(fixture_fixed("213.45"), BLOCKS, fixture_free_basic("60"))
    bill = calculate_bill(tariff, JULY, kwh("412.3"), VAT, free_basic_eligible=True)
    credits = [line for line in bill.lines if line.component == "free_basic"]
    assert [(line.quantity, line.amount) for line in credits] == [
        (Decimal(50), rand("-76.19")),
        (Decimal(10), rand("-20.11")),
    ]
    assert bill.subtotal == rand("957.34")
    assert bill.vat == rand("119.67")
    assert bill.total == rand("1077.01")


def test_without_eligibility_the_allocation_is_not_applied() -> None:
    with_allocation = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    without = fixture_version(BASIC, FLAT)
    bill = calculate_bill(with_allocation, JULY, kwh("120"), VAT, free_basic_eligible=False)
    assert [line.component for line in bill.lines] == ["basic", "energy"]
    assert bill.free_basic_eligible is False
    assert WarningCode.ASSUMED_FREE_BASIC_METHOD not in {w.code for w in bill.warnings}
    assert bill.total == calculate_bill(without, JULY, kwh("120"), VAT).total


def test_eligibility_must_be_given_for_a_tariff_with_an_allocation() -> None:
    tariff = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    with pytest.raises(FreeBasicEligibilityRequiredError):
        calculate_bill(tariff, JULY, kwh("10"), VAT)


def test_a_bill_records_eligibility_and_warns_about_the_assumed_method() -> None:
    tariff = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    bill = calculate_bill(tariff, JULY, kwh("10"), VAT, free_basic_eligible=True)
    assert bill.free_basic_eligible is True
    assert WarningCode.ASSUMED_FREE_BASIC_METHOD in {w.code for w in bill.warnings}
    unused = calculate_bill(tariff, JULY, kwh("0"), VAT, free_basic_eligible=True)
    assert unused.free_basic_eligible is True  # recorded even with nothing to credit
    assert WarningCode.ASSUMED_FREE_BASIC_METHOD not in {w.code for w in unused.warnings}
    plain = calculate_bill(fixture_version(BASIC, FLAT), JULY, kwh("10"), VAT)
    assert plain.free_basic_eligible is None


def test_use_exactly_equal_to_the_allocation_costs_no_energy() -> None:
    tariff = fixture_version(BASIC, FLAT, fixture_free_basic("50"))
    bill = calculate_bill(tariff, JULY, kwh("50"), VAT, free_basic_eligible=True)
    assert bill.lines[1].amount == rand("90.00")
    assert bill.lines[2].amount == rand("-90.00")
    assert bill.subtotal == rand("100.00")


def test_an_allocation_ending_on_a_threshold_gives_one_credit_line() -> None:
    # 50 kWh free, block 1 ends at 50: one credit (block 1), no zero-quantity second line.
    tariff = fixture_version(fixture_fixed("213.45"), BLOCKS, fixture_free_basic("50"))
    bill = calculate_bill(tariff, JULY, kwh("412.3"), VAT, free_basic_eligible=True)
    credits = [line for line in bill.lines if line.component == "free_basic"]
    assert [(line.quantity, line.amount) for line in credits] == [(Decimal(50), rand("-76.19"))]


def test_eligibility_on_a_tariff_without_an_allocation_is_refused() -> None:
    with pytest.raises(FreeBasicNotOfferedError):
        calculate_bill(fixture_version(BASIC, FLAT), JULY, kwh("10"), VAT, free_basic_eligible=True)


def test_an_allocation_refuses_a_part_month_only_when_it_applies() -> None:
    tariff = fixture_version(
        fixture_fixed("1.00", RateUnit.RAND_PER_DAY), FLAT, fixture_free_basic("50")
    )
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(tariff, PART_MONTH, kwh("10"), VAT, free_basic_eligible=True)
    bill = calculate_bill(tariff, PART_MONTH, kwh("10"), VAT, free_basic_eligible=False)
    assert bill.total.rand > 0


@pytest.mark.parametrize("mode", [RoundingMode.FLOOR, RoundingMode.CEILING])
def test_a_credit_cancels_its_charge_exactly_whatever_the_rounding_mode(
    mode: RoundingMode,
) -> None:
    # 30.5 kWh x 152.37c = 46.47285. Floor gives 46.47 for the charge; rounding the
    # credit -46.47285 with floor would give -46.48 and leave a cent. The credit is rounded
    # as its magnitude, so it is -46.47 and the energy costs nothing.
    cents = Quantisation(step=Decimal("0.01"), mode=mode)
    policy = fixture_policy(line_amount=cents, vat_amount=cents, total=cents)
    tariff = fixture_version(BASIC, fixture_flat("152.37"), fixture_free_basic("50"), policy=policy)
    bill = calculate_bill(tariff, JULY, kwh("30.5"), VAT, free_basic_eligible=True)
    energy, credit = bill.lines[1], bill.lines[2]
    assert credit.amount == Money.zero() - energy.amount
    assert bill.subtotal == rand("100.00")


def test_per_line_vat_on_a_credit_mirrors_the_charge() -> None:
    # Lines unrounded; VAT per line at cents, ceiling: energy 46.47285 x 12.5% = 5.80910625
    # -> 5.81; the credit's VAT is -5.81 (ceiling on -5.809... would give -5.80).
    ceiling = Quantisation(step=Decimal("0.01"), mode=RoundingMode.CEILING)
    policy = fixture_policy(
        line_amount=None, vat_application=VatApplication.PER_LINE, vat_amount=ceiling
    )
    tariff = fixture_version(fixture_flat("152.37"), fixture_free_basic("50"), policy=policy)
    bill = calculate_bill(tariff, JULY, kwh("30.5"), VAT, free_basic_eligible=True)
    assert [line.vat for line in bill.lines] == [rand("5.81"), rand("-5.81")]
    assert bill.total == Money.zero()


def test_a_credit_line_cites_the_allowance_and_the_rates_it_used() -> None:
    tariff = fixture_version(fixture_fixed("213.45"), BLOCKS, fixture_free_basic("60"))
    bill = calculate_bill(tariff, JULY, kwh("412.3"), VAT, free_basic_eligible=True)
    second_credit = [line for line in bill.lines if line.component == "free_basic"][1]
    assert [(s.role, s.citation.printed_text) for s in second_credit.sources] == [
        (SourceRole.RATE, "201.11"),
        (SourceRole.LOWER_THRESHOLD, "50"),
        (SourceRole.UPPER_THRESHOLD, "350"),
        (SourceRole.LABEL, "Free basic electricity"),
        (SourceRole.VAT_TREATMENT, "free basic VAT"),
        (SourceRole.FREE_ALLOWANCE, "60"),
    ]


def test_a_weaker_free_allowance_weakens_the_bill_only_when_it_applies() -> None:
    weak = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    base = fixture_free_basic("50")
    allocation = FreeBasicAllocation(
        schema_version=1,
        kind="free_basic_allocation",
        name=base.name,
        label=base.label,
        vat=base.vat,
        free_kwh=cited_decimal("50", weak),
        energy_component=base.energy_component,
    )
    tariff = fixture_version(BASIC, FLAT, allocation)
    eligible = calculate_bill(tariff, JULY, kwh("120"), VAT, free_basic_eligible=True)
    not_eligible = calculate_bill(tariff, JULY, kwh("120"), VAT, free_basic_eligible=False)
    assert eligible.status is StatusKind.USER_PROVIDED
    assert not_eligible.status is StatusKind.ESTIMATED


# ------------------------------------------------------------- component validation


@pytest.mark.parametrize("free", ["0", "-5", "-0"])
def test_an_allocation_must_be_positive(free: str) -> None:
    with pytest.raises(ValidationError):
        fixture_free_basic(free)


@pytest.mark.parametrize(
    "components",
    [
        (BASIC, FLAT, fixture_free_basic("50", energy_component="missing")),
        (BASIC, FLAT, fixture_free_basic("50", energy_component="basic")),
        (FLAT, fixture_free_basic("50"), fixture_free_basic("60", name="second")),
        (FLAT, fixture_free_basic("50", vat=VatTreatment.ZERO_RATED)),
    ],
    ids=["unknown component", "not an energy component", "two allocations", "other VAT"],
)
def test_an_allocation_must_name_one_energy_component(
    components: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError):
        fixture_version(*components)  # type: ignore[arg-type]


def test_new_components_survive_a_json_round_trip() -> None:
    tariff = fixture_version(
        BASIC, BLOCKS, fixture_levy("2.5"), fixture_free_basic("50.5", energy_component="energy")
    )
    again = TariffVersion.model_validate_json(tariff.model_dump_json())
    assert again == tariff
    assert isinstance(again.components[2], Levy)
    assert isinstance(again.components[3], FreeBasicAllocation)
    assert again.free_basic_allocation == again.components[3]
