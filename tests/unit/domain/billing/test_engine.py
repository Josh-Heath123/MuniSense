"""The forward engine for one billing period (P1-7). Fixture tariffs only, hand-checked.

The fixture VAT rate is 12.5%, deliberately not South Africa's real rate.
"""

from datetime import date
from decimal import Decimal

import pytest

from munisense.domain.billing import (
    BillingPeriod,
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
    PeriodTotal,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    UnsupportedPriceBasisError,
    WarningCode,
    calculate_bill,
)
from munisense.domain.citations import StatusKind, TextCheck, Verified
from munisense.domain.money import Money, NoVatRateError, RateUnit, VatApplication
from munisense.domain.tariffs import PriceBasis, VatTreatment
from support.builders import (
    CENTS_HALF_UP,
    fixture_blocks,
    fixture_fixed,
    fixture_flat,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
BLOCKS = fixture_blocks(("50", "152.37"), ("350", "201.11"), (None, "257.89"))
BASIC = fixture_fixed("213.45")
VAT = fixture_vat_table()


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


def test_a_block_tariff_bill_is_reproduced_to_the_cent() -> None:
    # Hand calculation, 412.3 kWh in July 2026, lines rounded to cents half up,
    # VAT once on the subtotal:
    #   basic charge       1 month x R213.45                 = 213.45
    #   block 1 (0-50)     50    kWh x 152.37c = 76.185      ->  76.19
    #   block 2 (50-350)   300   kWh x 201.11c = 603.33      -> 603.33
    #   block 3 (>350)     62.3  kWh x 257.89c = 160.66547   -> 160.67
    #   subtotal comes to R1053.64
    #   VAT 12.5% of 1053.64 = 131.705                       ->  131.71
    #   total comes to R1185.35
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    assert [line.amount for line in bill.lines] == [
        rand("213.45"),
        rand("76.19"),
        rand("603.33"),
        rand("160.67"),
    ]
    assert [line.quantity for line in bill.lines] == [
        Decimal(1),
        Decimal(50),
        Decimal(300),
        Decimal("62.3"),
    ]
    assert bill.subtotal == rand("1053.64")
    assert bill.vat == rand("131.71")
    assert bill.total == rand("1185.35")


def test_vat_per_line_is_rounded_on_each_line() -> None:
    # Same bill, VAT per line: 26.68125 -> 26.68, 9.52375 -> 9.52, 75.41625 -> 75.42,
    # 20.08375 -> 20.08; VAT 131.70; total 1185.34.
    policy = fixture_policy(vat_application=VatApplication.PER_LINE)
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS, policy=policy), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    assert [line.vat for line in bill.lines] == [
        rand("26.68"),
        rand("9.52"),
        rand("75.42"),
        rand("20.08"),
    ]
    assert bill.vat == rand("131.70")
    assert bill.total == rand("1185.34")


def test_without_line_rounding_amounts_stay_exact_until_the_total() -> None:
    # 76.185 + 603.33 + 160.66547 + 213.45 = 1053.63047; VAT 131.70380875 -> 131.70;
    # total 1053.63047 + 131.70 = 1185.33047 -> 1185.33
    policy = fixture_policy(line_amount=None)
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS, policy=policy), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    assert bill.lines[3].amount == rand("160.66547")
    assert bill.subtotal == rand("1053.63047")
    assert bill.vat == rand("131.70")
    assert bill.total == rand("1185.33")


def test_a_daily_fixed_charge_counts_the_days_of_the_period() -> None:
    # R7.00 a day for the 31 days of July = R217.00; flat 180c x 100 kWh = R180.00.
    tariff = fixture_version(fixture_fixed("7.00", RateUnit.RAND_PER_DAY), fixture_flat("180.00"))
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("100")), VAT)
    assert bill.lines[0].quantity == Decimal(31)
    assert bill.lines[0].amount == rand("217.00")
    assert bill.subtotal == rand("397.00")


def test_a_daily_charge_and_flat_energy_work_for_a_period_that_is_not_a_month() -> None:
    tariff = fixture_version(fixture_fixed("7.00", RateUnit.RAND_PER_DAY), fixture_flat("180.00"))
    period = BillingPeriod(start=date(2026, 7, 10), end=date(2026, 8, 12))
    bill = calculate_bill(tariff, period, PeriodTotal(kwh=Decimal("100")), VAT)
    assert bill.lines[0].quantity == Decimal(33)


def test_zero_consumption_charges_only_the_fixed_charge() -> None:
    bill = calculate_bill(fixture_version(BASIC, BLOCKS), JULY, PeriodTotal(kwh=Decimal(0)), VAT)
    assert [line.component for line in bill.lines] == ["basic"]
    assert bill.subtotal == rand("213.45")


def test_zero_rated_and_exempt_lines_carry_no_vat() -> None:
    free = fixture_blocks((None, "100.00"), name="levy", vat=VatTreatment.ZERO_RATED)
    exempt = fixture_blocks((None, "100.00"), name="exempt", vat=VatTreatment.EXEMPT)
    tariff = fixture_version(fixture_flat("100.00"), free, exempt)
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("10")), VAT)
    assert bill.subtotal == rand("30.00")
    assert bill.vat == rand("1.25")  # 12.5% of the standard-rated R10.00 only
    assert [line.vat for line in bill.lines] == [None, None, None]  # VAT on the subtotal


# ------------------------------------------------------------------------- provenance


def test_every_line_cites_the_values_it_used() -> None:
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    block_2 = bill.lines[2]
    printed = {citation.printed_text for citation in block_2.sources}
    # the rate, both thresholds that bound the block, the label and the VAT treatment
    assert {"201.11", "50", "350", "Energy charge"} <= printed
    assert block_2.status is StatusKind.ESTIMATED
    assert all(line.sources for line in bill.lines)
    assert bill.vat_rate.percent.value == Decimal("12.5")


def test_every_result_warns_about_unverified_values_and_rounding() -> None:
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    codes = {warning.code for warning in bill.warnings}
    assert codes == {WarningCode.UNVERIFIED_VALUES, WarningCode.UNVERIFIED_ROUNDING_POLICY}
    assert bill.status is StatusKind.ESTIMATED
    assert bill.rounding_policy == "fixture"


# --------------------------------------------------------------------------- refusals


def test_time_of_use_consumption_is_refused() -> None:
    profile = TimeOfUseBuckets(kwh_by_bucket={"peak": Decimal("10")})
    with pytest.raises(UnsupportedConsumptionError):
        calculate_bill(fixture_version(BASIC, BLOCKS), JULY, profile, VAT)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 6, 1), date(2026, 7, 1)),  # before the version
        (date(2027, 6, 15), date(2027, 7, 15)),  # runs past the version's end
    ],
)
def test_a_period_outside_the_version_is_refused(start: date, end: date) -> None:
    with pytest.raises(PeriodOutsideVersionError):
        calculate_bill(
            fixture_version(BLOCKS),
            BillingPeriod(start=start, end=end),
            PeriodTotal(kwh=Decimal("1")),
            VAT,
        )


@pytest.mark.parametrize("component", [BLOCKS, BASIC])
def test_monthly_values_refuse_a_period_that_is_not_a_calendar_month(component: object) -> None:
    period = BillingPeriod(start=date(2026, 7, 10), end=date(2026, 8, 12))
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(
            fixture_version(component),  # type: ignore[arg-type]  # both are components
            period,
            PeriodTotal(kwh=Decimal("1")),
            VAT,
        )


def test_prices_including_vat_are_refused_until_supported() -> None:
    tariff = fixture_version(BLOCKS, basis=PriceBasis.INCLUDING_VAT)
    with pytest.raises(UnsupportedPriceBasisError):
        calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("1")), VAT)


def test_a_period_without_a_vat_rate_is_refused() -> None:
    old = fixture_version(BLOCKS, start=date(1999, 1, 1), end=None)
    period = BillingPeriod(start=date(1999, 7, 1), end=date(1999, 8, 1))
    with pytest.raises(NoVatRateError):
        calculate_bill(old, period, PeriodTotal(kwh=Decimal("1")), VAT)


def test_the_policy_quantisations_are_named_not_hard_coded() -> None:
    policy = fixture_policy(total=None, vat_amount=None, line_amount=None)
    bill = calculate_bill(
        fixture_version(fixture_flat("100.001")), JULY, PeriodTotal(kwh=Decimal("1")), VAT
    )
    assert bill.total == rand("1.13")  # the default fixture policy rounds
    unrounded = calculate_bill(
        fixture_version(fixture_flat("100.001"), policy=policy),
        JULY,
        PeriodTotal(kwh=Decimal("1")),
        VAT,
    )
    # 1.00001 + 12.5% = 1.12501125, nothing rounded
    assert unrounded.total == rand("1.12501125")
    assert CENTS_HALF_UP.apply(unrounded.total.rand) == Decimal("1.13")


def test_flat_energy_at_zero_consumption_has_no_energy_line() -> None:
    tariff = fixture_version(fixture_fixed("7.00", RateUnit.RAND_PER_DAY), fixture_flat("180.00"))
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal(0)), VAT)
    assert [line.component for line in bill.lines] == ["basic"]


def test_a_citation_shared_by_two_values_is_listed_once() -> None:
    # The fixture label and VAT treatment are both printed as "Energy charge"/"fixture";
    # a block whose threshold prints the same text as its rate shares one citation.
    shared = fixture_blocks(("100", "100"), (None, "100"))
    bill = calculate_bill(fixture_version(shared), JULY, PeriodTotal(kwh=Decimal("150")), VAT)
    sources = bill.lines[1].sources
    assert len(sources) == len(set(sources))
    assert [c.printed_text for c in sources].count("100") == 1


def test_a_fully_verified_bill_carries_no_warnings() -> None:
    verified = Verified(
        verifier="owner",
        verifier_kind="human",
        method="fixture",
        verified_on=date(2026, 11, 17),
        text_check=TextCheck.PASSED,
    )
    tariff = fixture_version(
        fixture_fixed("213.45", status=verified),
        fixture_blocks(("50", "152.37"), (None, "201.11"), status=verified),
        status=verified,
    )
    vat = fixture_vat_table(status=verified)
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("412.3")), vat)
    assert bill.status is StatusKind.VERIFIED
    assert bill.rounding_policy_status is StatusKind.VERIFIED
    assert bill.warnings == ()
