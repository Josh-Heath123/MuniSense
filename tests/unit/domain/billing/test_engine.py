"""The forward engine for one billing period (P1-7). Fixture tariffs only, hand-checked.

The fixture VAT rate is 12.5%, deliberately not South Africa's real rate.
"""

from datetime import date
from decimal import Decimal

import pytest

from munisense.domain.base import DomainError
from munisense.domain.billing import (
    Bill,
    BillingPeriod,
    LineItem,
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
    PeriodTotal,
    SourceRole,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    UnsupportedPriceBasisError,
    WarningCode,
    calculate_bill,
)
from munisense.domain.citations import ProvidedBy, StatusKind, TextCheck, UserProvided, Verified
from munisense.domain.money import (
    Money,
    NoVatRateError,
    Quantisation,
    Rate,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    VatApplication,
    VatRate,
    VatTable,
)
from munisense.domain.tariffs import (
    Block,
    BlockEnergy,
    Component,
    PriceBasis,
    TariffVersion,
    TouPeriod,
    VatTreatment,
)
from support.builders import (
    CENTS_HALF_UP,
    cited_basis,
    cited_date,
    cited_decimal,
    cited_label,
    cited_rate,
    cited_vat,
    fixture_billing_policy,
    fixture_blocks,
    fixture_fixed,
    fixture_flat,
    fixture_levy,
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


# Each rounding point has its own step and mode, so using one point's quantisation at
# another changes the result: lines 0.01 half-even, VAT 0.01 ceiling, total 0.1 half-up.
def distinct_points(vat_application: VatApplication) -> RoundingPolicy:
    return fixture_policy(
        line_amount=Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_EVEN),
        vat_application=vat_application,
        vat_amount=Quantisation(step=Decimal("0.01"), mode=RoundingMode.CEILING),
        total=Quantisation(step=Decimal("0.1"), mode=RoundingMode.HALF_UP),
    )


def test_each_rounding_point_uses_its_own_quantisation_on_the_subtotal() -> None:
    # 412.3 kWh, as above, with the distinct points:
    #   basic 213.45; block 1 76.185 -> 76.18 (half-even keeps the even 8; half-up gives
    #   76.19); block 2 603.33; block 3 160.66547 -> 160.67
    #   subtotal 213.45 + 76.18 + 603.33 + 160.67 = 1053.63
    #   VAT 12.5% x 1053.63 = 131.70375 -> 131.71 (ceiling; half-up gives 131.70)
    #   total 1053.63 + 131.71 = 1185.34 -> 1185.3 (0.1 half-up)
    policy = distinct_points(VatApplication.ON_SUBTOTAL)
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS, policy=policy), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    assert [line.amount for line in bill.lines] == [
        rand("213.45"),
        rand("76.18"),
        rand("603.33"),
        rand("160.67"),
    ]
    assert bill.subtotal == rand("1053.63")
    assert bill.vat == rand("131.71")
    assert bill.total == rand("1185.3")


def test_each_rounding_point_uses_its_own_quantisation_per_line() -> None:
    # Same lines; VAT per line at 0.01 ceiling (half-even would give 26.68, 9.52, 75.42,
    # 20.08):
    #   213.45 x 12.5% = 26.68125 -> 26.69     76.18 x 12.5% = 9.5225 -> 9.53
    #   603.33 x 12.5% = 75.41625 -> 75.42     160.67 x 12.5% = 20.08375 -> 20.09
    #   VAT 26.69 + 9.53 + 75.42 + 20.09 = 131.73
    #   total 1053.63 + 131.73 = 1185.36 -> 1185.4 (0.1 half-up)
    policy = distinct_points(VatApplication.PER_LINE)
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS, policy=policy), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    assert [line.vat for line in bill.lines] == [
        rand("26.69"),
        rand("9.53"),
        rand("75.42"),
        rand("20.09"),
    ]
    assert bill.vat == rand("131.73")
    assert bill.total == rand("1185.4")


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


def _roles(line: LineItem) -> dict[SourceRole, str]:
    return {source.role: source.citation.printed_text for source in line.sources}


def test_every_line_cites_each_value_it_used_by_role() -> None:
    bill = calculate_bill(
        fixture_version(BASIC, BLOCKS), JULY, PeriodTotal(kwh=Decimal("412.3")), VAT
    )
    basic, block_1, block_2, block_3 = bill.lines
    common = {SourceRole.LABEL, SourceRole.VAT_TREATMENT}
    assert _roles(basic).keys() == {SourceRole.RATE} | common
    assert _roles(basic)[SourceRole.RATE] == "213.45"
    assert _roles(block_1) == {
        SourceRole.RATE: "152.37",
        SourceRole.UPPER_THRESHOLD: "50",
        SourceRole.LABEL: "Energy charge",
        SourceRole.VAT_TREATMENT: "fixture",
    }
    assert _roles(block_2)[SourceRole.LOWER_THRESHOLD] == "50"
    assert _roles(block_2)[SourceRole.UPPER_THRESHOLD] == "350"
    assert _roles(block_3)[SourceRole.LOWER_THRESHOLD] == "350"
    assert SourceRole.UPPER_THRESHOLD not in _roles(block_3)
    assert bill.vat_rate.percent.value == Decimal("12.5")


def test_the_bill_names_the_version_it_used() -> None:
    bill = calculate_bill(fixture_version(BLOCKS), JULY, PeriodTotal(kwh=Decimal("1")), VAT)
    assert (bill.tariff_name, bill.version_effective_from, bill.version_effective_to) == (
        "Fixture tariff",
        date(2026, 7, 1),
        date(2027, 7, 1),
    )


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
    profile = TimeOfUseBuckets(used_kwh={TouPeriod.PEAK: Decimal("10")})
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
def test_monthly_values_refuse_a_period_that_is_not_a_calendar_month(component: Component) -> None:
    period = BillingPeriod(start=date(2026, 7, 10), end=date(2026, 8, 12))
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(fixture_version(component), period, PeriodTotal(kwh=Decimal("1")), VAT)


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


def test_per_line_vat_is_zero_on_zero_rated_and_exempt_lines() -> None:
    free = fixture_blocks((None, "100.00"), name="levy", vat=VatTreatment.ZERO_RATED)
    exempt = fixture_blocks((None, "100.00"), name="exempt", vat=VatTreatment.EXEMPT)
    policy = fixture_policy(vat_application=VatApplication.PER_LINE)
    bill = calculate_bill(
        fixture_version(fixture_flat("100.00"), free, exempt, policy=policy),
        JULY,
        PeriodTotal(kwh=Decimal("10")),
        VAT,
    )
    assert [line.vat for line in bill.lines] == [rand("1.25"), Money.zero(), Money.zero()]
    assert bill.vat == rand("1.25")


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        (date(2028, 2, 1), date(2028, 3, 1), 29),  # leap-year February
        (date(2026, 12, 1), date(2027, 1, 1), 31),  # December into January
    ],
)
def test_calendar_month_edge_cases(start: date, end: date, days: int) -> None:
    tariff = fixture_version(fixture_fixed("1.00", RateUnit.RAND_PER_DAY), BLOCKS, end=None)
    bill = calculate_bill(
        tariff, BillingPeriod(start=start, end=end), PeriodTotal(kwh=Decimal("60")), VAT
    )
    assert bill.lines[0].quantity == Decimal(days)


def test_a_flat_energy_tariff_at_zero_consumption_has_no_lines() -> None:
    bill = calculate_bill(
        fixture_version(fixture_flat("180.00")), JULY, PeriodTotal(kwh=Decimal(0)), VAT
    )
    assert bill.lines == ()
    assert bill.total == Money.zero()


def test_a_very_long_period_costs_no_more_work_than_a_short_one() -> None:
    # Work grows with components and blocks, not days: 7,000 years is one line per component.
    tariff = fixture_version(
        fixture_fixed("1.00", RateUnit.RAND_PER_DAY), fixture_flat("100.00"), end=None
    )
    period = BillingPeriod(start=date(2026, 7, 1), end=date(9000, 1, 1))
    bill = calculate_bill(tariff, period, PeriodTotal(kwh=Decimal("5")), VAT)
    assert bill.lines[0].quantity == Decimal(period.days)
    assert len(bill.lines) == 2


def test_an_amount_too_wide_to_hold_exactly_is_a_domain_error() -> None:
    # Each value is in range (Python mode allows 60 digits), but the product is not: the
    # engine must refuse with a domain error, never a validation error.
    tariff = fixture_version(
        fixture_flat("1E+40"), policy=fixture_policy(line_amount=None, vat_amount=None, total=None)
    )
    with pytest.raises(DomainError):
        calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("1E+30")), VAT)
    with pytest.raises(DomainError):
        Rate(value=Decimal("1E-40"), unit=RateUnit.CENTS_PER_KWH).charge(Decimal("1E-30"))


@pytest.mark.parametrize("exponent", [-59, -60])
def test_a_rate_at_the_low_edge_of_the_exact_range_is_a_domain_error(exponent: int) -> None:
    # The rate is valid as printed, but in rand per kWh (cents shifted by -2) it is
    # narrower than an exact amount can hold.
    tariff = fixture_version(fixture_flat(f"1E{exponent}"))
    with pytest.raises(DomainError):
        calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal(1)), VAT)


# ------------------------------------------------------- one weaker source at a time

VERIFIED = Verified(
    verifier="owner",
    verifier_kind="human",
    method="fixture",
    verified_on=date(2026, 11, 17),
    text_check=TextCheck.PASSED,
)
USER = UserProvided(provided_by=ProvidedBy.OWNER_BILL)


def _bill_with_one_weak(weak: str | None) -> Bill:
    def status(position: str) -> Verified | UserProvided:
        return USER if position == weak else VERIFIED

    energy = BlockEnergy(
        schema_version=1,
        kind="block_energy",
        name="energy",
        label=cited_label("Energy charge", status("label")),
        vat=cited_vat(status=status("vat_treatment")),
        blocks=(
            Block(
                up_to_kwh=cited_decimal("50", status("threshold")),
                rate=cited_rate("150", RateUnit.CENTS_PER_KWH, status("rate_1")),
            ),
            Block(up_to_kwh=None, rate=cited_rate("250", RateUnit.CENTS_PER_KWH, status("rate_2"))),
        ),
    )
    tariff = TariffVersion(
        schema_version=1,
        supplier="fixture-metro",
        tariff_code="fixture-a",
        customer_class="residential",
        printed_name=cited_label("Fixture tariff", status("printed_name")),
        applies_to=cited_label("Fixture customers", status("applies_to")),
        effective_from=cited_date(date(2026, 7, 1), status("effective_from")),
        effective_to=cited_date(date(2027, 7, 1), status("effective_to")),
        price_basis=cited_basis(status=status("price_basis")),
        rounding_policy=fixture_policy(status=status("policy")),
        billing_policy=fixture_billing_policy(),
        components=(energy,),
    )
    vat = VatTable(
        rates=(
            VatRate(
                start_cited=cited_date(date(2000, 1, 1), status("vat_start")),
                end_cited=None,
                percent=cited_decimal("12.5", status("vat_percent")),
            ),
        )
    )
    return calculate_bill(tariff, JULY, PeriodTotal(kwh=Decimal("100")), vat)


VALUE_POSITIONS = [
    "label",
    "vat_treatment",
    "threshold",
    "rate_1",
    "rate_2",
    "printed_name",
    "applies_to",
    "effective_from",
    "effective_to",
    "price_basis",
    "vat_start",
    "vat_percent",
]


def test_a_fully_verified_bill_has_no_warnings_and_verified_lines() -> None:
    bill = _bill_with_one_weak(None)
    assert bill.status is StatusKind.VERIFIED
    assert all(line.status is StatusKind.VERIFIED for line in bill.lines)
    assert bill.warnings == ()


@pytest.mark.parametrize("weak", VALUE_POSITIONS)
def test_one_weaker_value_makes_the_bill_warn(weak: str) -> None:
    bill = _bill_with_one_weak(weak)
    assert bill.status is StatusKind.USER_PROVIDED
    assert {w.code for w in bill.warnings} == {WarningCode.UNVERIFIED_VALUES}


@pytest.mark.parametrize(
    ("weak", "weak_lines"),
    [
        ("label", [0, 1]),
        ("vat_treatment", [0, 1]),
        ("threshold", [0, 1]),  # upper bound of block 1, lower bound of block 2
        ("rate_1", [0]),
        ("rate_2", [1]),
        ("printed_name", []),
    ],
)
def test_a_line_is_as_weak_as_the_values_it_used(weak: str, weak_lines: list[int]) -> None:
    bill = _bill_with_one_weak(weak)
    actual = [i for i, line in enumerate(bill.lines) if line.status is StatusKind.USER_PROVIDED]
    assert actual == weak_lines


def test_an_unverified_rounding_policy_alone_gives_only_its_warning() -> None:
    bill = _bill_with_one_weak("policy")
    assert bill.status is StatusKind.VERIFIED
    assert bill.rounding_policy_status is StatusKind.USER_PROVIDED
    assert {w.code for w in bill.warnings} == {WarningCode.UNVERIFIED_ROUNDING_POLICY}


def test_a_whole_month_of_a_monthly_charge_is_one_month() -> None:
    bill = calculate_bill(fixture_version(BASIC), JULY, PeriodTotal(kwh=Decimal(0)), VAT)
    assert bill.lines[0].description == "1 month"
    assert bill.lines[0].quantity == Decimal(1)


def test_a_flat_energy_line_says_all_kwh() -> None:
    bill = calculate_bill(
        fixture_version(fixture_flat("100.00")), JULY, PeriodTotal(kwh=Decimal(10)), VAT
    )
    assert bill.lines[0].description == "all kWh"


def test_a_per_kwh_levy_line_says_all_kwh() -> None:
    bill = calculate_bill(
        fixture_version(fixture_flat("100.00"), fixture_levy("2.5")),
        JULY,
        PeriodTotal(kwh=Decimal(10)),
        VAT,
    )
    assert bill.lines[1].description == "all kWh"
