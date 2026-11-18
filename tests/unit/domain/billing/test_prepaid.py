"""P1-14: prepaid purchases.

Fixture tariffs only (invented values, fixture VAT 12.5%). Blocks: 50 kWh at 152.37c, to
350 kWh at 201.11c, then 257.89c; with VAT one kWh costs R1.7141625, R2.2624875 and
R2.9012625. Unless a test says otherwise the policy rounds the kWh of a purchase once to
hundredths, half up; fixed charges and their VAT round to cents, half up.
"""

from datetime import date
from decimal import Decimal

import pytest

from munisense.domain.billing import (
    FreeBasicEligibilityRequiredError,
    InvalidPurchaseError,
    MonthSoFar,
    PeriodCrossesSeasonError,
    PeriodOutsideVersionError,
    PrepaidNotSupportedError,
    PrepaidPrecisionError,
    PurchasesNotInOneMonthError,
    PurchaseTooSmallError,
    SourceRole,
    WarningCode,
    calculate_month,
    calculate_purchase,
)
from munisense.domain.citations import Cited, ProvidedBy, StatusKind, UserProvided, Verified
from munisense.domain.citations.model import TextCheck
from munisense.domain.money import (
    InexactArithmeticError,
    Money,
    Quantisation,
    RateUnit,
    RoundingMode,
    VatRate,
    VatRateChangesError,
    VatTable,
)
from munisense.domain.tariffs import (
    BillingPolicy,
    Component,
    PrepaidFixedCharges,
    Season,
    SeasonDates,
    TariffVersion,
    VatTreatment,
)
from support.builders import (
    cited_date,
    cited_decimal,
    cited_label,
    fixture_billing_policy,
    fixture_blocks,
    fixture_fixed,
    fixture_flat,
    fixture_free_basic,
    fixture_levy,
    fixture_policy,
    fixture_season,
    fixture_seasonal,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
BLOCKS = fixture_blocks(("50", "152.37"), ("350", "201.11"), (None, "257.89"))
HUNDREDTHS_UP = Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_UP)
HUNDREDTHS_DOWN = Quantisation(step=Decimal("0.01"), mode=RoundingMode.DOWN)
FIRST = fixture_billing_policy()
NOT_FROM_PURCHASES = fixture_billing_policy(fixed_charges=PrepaidFixedCharges.NOT_FROM_PURCHASES)
NOTHING_YET = MonthSoFar(purchases=0, kwh=Decimal(0))


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


def tariff(
    *components: Component,
    point: Quantisation = HUNDREDTHS_UP,
    billing: BillingPolicy = FIRST,
) -> TariffVersion:
    return fixture_version(*components, policy=fixture_policy(prepaid_kwh=point), billing=billing)


# -------------------------------------------------------------------- one purchase


def test_a_purchase_that_crosses_a_block_threshold() -> None:
    # 30 kWh already bought this month; R200.00; no fixed charges from purchases;
    # kWh rounded down to hundredths.
    #   block 1: 20 kWh left x R1.7141625 = R34.28325; R165.71675 left
    #   block 2: 165.71675 / 2.2624875 = 73.2455... kWh
    #   total 20 + 73.2455... = 93.2455... -> 93.24 kWh (down); month now 123.24 kWh
    version = tariff(BLOCKS, point=HUNDREDTHS_DOWN, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(30))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("200.00"), so_far, VAT)
    assert purchase.kwh == Decimal("93.24")
    assert purchase.month_kwh_after == Decimal("123.24")
    first, second = purchase.segments
    assert (first.from_kwh, first.to_kwh, first.kwh) == (Decimal(30), Decimal(50), Decimal(20))
    assert first.price_per_kwh == Decimal("1.7141625")
    assert first.amount == rand("34.28325")
    assert (second.from_kwh, second.to_kwh, second.kwh) == (
        Decimal(50),
        Decimal(350),
        Decimal("73.24"),
    )
    assert second.amount == rand("165.71675")


def test_the_first_purchase_of_the_month_pays_the_fixed_charges() -> None:
    # Basic R100.00 a month + VAT 12.50 = 112.50 from the first purchase of R150.00;
    # R37.50 buys 37.5 / 1.7141625 = 21.8766... -> 21.88 kWh
    version = tariff(fixture_fixed("100.00"), BLOCKS)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("150.00"), NOTHING_YET, VAT)
    assert purchase.fixed_charges == rand("112.50")
    assert [line.amount for line in purchase.fixed_lines] == [rand("100.00")]
    assert purchase.energy_amount == rand("37.50")
    assert purchase.kwh == Decimal("21.88")


def test_a_month_of_several_purchases() -> None:
    # 1 July R150.00: fixed 112.50; 21.88 kWh (above). Month 21.88.
    # 10 July R100.00: 28.12 kWh of block 1 for 28.12 x 1.7141625 = 48.2022495; R51.7977505
    #   left buys 51.7977505 / 2.2624875 = 22.894... in block 2; total 51.0144... -> 51.01.
    #   Month 72.89.
    # 20 July R400.00: 400 / 2.2624875 = 176.7965... -> 176.80, all in block 2. Month 249.69.
    version = tariff(fixture_fixed("100.00"), BLOCKS)
    purchases = calculate_month(
        version,
        [
            (date(2026, 7, 1), rand("150.00")),
            (date(2026, 7, 10), rand("100.00")),
            (date(2026, 7, 20), rand("400.00")),
        ],
        VAT,
    )
    assert [p.kwh for p in purchases] == [Decimal("21.88"), Decimal("51.01"), Decimal("176.80")]
    assert [p.fixed_charges for p in purchases] == [rand("112.50"), Money.zero(), Money.zero()]
    assert purchases[-1].month_kwh_after == Decimal("249.69")


def test_without_deductions_the_fixed_charges_are_not_taken_from_purchases() -> None:
    version = tariff(fixture_fixed("100.00"), BLOCKS, billing=NOT_FROM_PURCHASES)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("37.50"), NOTHING_YET, VAT)
    assert purchase.fixed_charges == Money.zero()
    assert purchase.kwh == Decimal("21.88")


def test_a_per_kwh_levy_and_zero_rated_parts_are_priced_per_kwh() -> None:
    # Flat 100c (standard) + levy 10c (zero-rated): one kWh costs 1.125 + 0.10 = R1.225;
    # R49.00 buys 40 kWh exactly.
    levy = fixture_levy("10.00", vat=VatTreatment.ZERO_RATED)
    version = tariff(fixture_flat("100.00"), levy, billing=NOT_FROM_PURCHASES)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("49.00"), NOTHING_YET, VAT)
    assert purchase.segments[0].price_per_kwh == Decimal("1.225")
    assert purchase.kwh == Decimal("40.00")


def test_a_seasonal_tariff_uses_the_season_of_the_purchase_day() -> None:
    # High season (June to August) 300c, low 200c: R33.75 buys 10 kWh in July (3.375/kWh)
    # and 15 kWh in October (2.25/kWh).
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300.00")),
        fixture_season("low", (9, 1), (5, 31), (None, "200.00")),
    )
    version = tariff(seasonal, billing=NOT_FROM_PURCHASES)
    july = calculate_purchase(version, date(2026, 7, 5), rand("33.75"), NOTHING_YET, VAT)
    october = calculate_purchase(version, date(2026, 10, 5), rand("33.75"), NOTHING_YET, VAT)
    assert (july.kwh, october.kwh) == (Decimal("10.00"), Decimal("15.00"))


def test_a_segment_cites_the_rate_and_thresholds_it_used() -> None:
    version = tariff(BLOCKS, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(60))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("10.00"), so_far, VAT)
    (segment,) = purchase.segments
    assert [(s.role, s.citation.printed_text) for s in segment.sources] == [
        (SourceRole.RATE, "201.11"),
        (SourceRole.LABEL, "Energy charge"),
        (SourceRole.VAT_TREATMENT, "fixture"),
        (SourceRole.LOWER_THRESHOLD, "50"),
        (SourceRole.UPPER_THRESHOLD, "350"),
    ]


def test_a_purchase_warns_about_unverified_values_and_policies() -> None:
    version = tariff(BLOCKS)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("10.00"), NOTHING_YET, VAT)
    assert {w.code for w in purchase.warnings} == {
        WarningCode.UNVERIFIED_VALUES,
        WarningCode.UNVERIFIED_ROUNDING_POLICY,
        WarningCode.UNVERIFIED_BILLING_POLICY,
    }


def test_exactly_enough_for_the_fixed_charges_buys_nothing() -> None:
    version = tariff(fixture_fixed("100.00"), BLOCKS)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("112.50"), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal("0.00")
    assert purchase.segments == ()


# ------------------------------------------------------------------------- refusals


def test_a_purchase_smaller_than_the_fixed_charges_is_refused() -> None:
    version = tariff(fixture_fixed("100.00"), BLOCKS)
    with pytest.raises(PurchaseTooSmallError):
        calculate_purchase(version, date(2026, 7, 1), rand("100.00"), NOTHING_YET, VAT)


def test_a_day_outside_the_version_is_refused() -> None:
    with pytest.raises(PeriodOutsideVersionError):
        calculate_purchase(tariff(BLOCKS), date(2027, 7, 1), rand("10.00"), NOTHING_YET, VAT)


def test_fixed_charges_need_the_whole_month_in_the_version() -> None:
    version = fixture_version(
        fixture_fixed("100.00"),
        BLOCKS,
        start=date(2026, 7, 15),
        policy=fixture_policy(prepaid_kwh=HUNDREDTHS_UP),
    )
    with pytest.raises(PeriodOutsideVersionError):
        calculate_purchase(version, date(2026, 7, 20), rand("200.00"), NOTHING_YET, VAT)


def test_free_basic_electricity_on_prepaid_is_not_built() -> None:
    version = tariff(fixture_flat("100.00"), fixture_free_basic("50"), billing=NOT_FROM_PURCHASES)
    with pytest.raises(PrepaidNotSupportedError):
        calculate_purchase(
            version,
            date(2026, 7, 1),
            rand("10.00"),
            NOTHING_YET,
            VAT,
            free_basic_eligible=True,
        )
    with pytest.raises(FreeBasicEligibilityRequiredError):
        calculate_purchase(version, date(2026, 7, 1), rand("10.00"), NOTHING_YET, VAT)
    not_eligible = calculate_purchase(
        version,
        date(2026, 7, 1),
        rand("11.25"),
        NOTHING_YET,
        VAT,
        free_basic_eligible=False,
    )
    assert not_eligible.kwh == Decimal("10.00")


def test_free_energy_with_money_left_is_refused() -> None:
    version = tariff(fixture_flat("0"), billing=NOT_FROM_PURCHASES)
    with pytest.raises(PrepaidNotSupportedError):
        calculate_purchase(version, date(2026, 7, 1), rand("1.00"), NOTHING_YET, VAT)


def test_without_a_prepaid_point_an_inexact_purchase_is_refused() -> None:
    version = fixture_version(BLOCKS, billing=NOT_FROM_PURCHASES, policy=fixture_policy())
    with pytest.raises(InexactArithmeticError):
        calculate_purchase(version, date(2026, 7, 1), rand("10.00"), NOTHING_YET, VAT)
    exact = fixture_version(
        fixture_flat("100.00"), billing=NOT_FROM_PURCHASES, policy=fixture_policy()
    )
    purchase = calculate_purchase(exact, date(2026, 7, 1), rand("11.25"), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal(10)


@pytest.mark.parametrize(
    "days",
    [
        [date(2026, 7, 1), date(2026, 8, 1)],
        [date(2026, 7, 10), date(2026, 7, 1)],
    ],
    ids=["two months", "out of order"],
)
def test_a_month_of_purchases_must_be_one_month_in_order(days: list[date]) -> None:
    with pytest.raises(PurchasesNotInOneMonthError):
        calculate_month(tariff(BLOCKS), [(day, rand("10.00")) for day in days], VAT)


def test_an_empty_month_has_no_purchases() -> None:
    assert calculate_month(tariff(BLOCKS), [], VAT) == ()


def test_a_daily_charge_is_deducted_for_the_whole_month() -> None:
    # R1.00 a day for July (31 days) + VAT 3.875 -> 3.88: 34.88 from the first purchase.
    version = tariff(fixture_fixed("1.00", RateUnit.RAND_PER_DAY), BLOCKS)
    purchase = calculate_purchase(version, date(2026, 7, 9), rand("50.00"), NOTHING_YET, VAT)
    assert purchase.fixed_charges == rand("34.88")


def test_a_fully_verified_purchase_has_no_warnings() -> None:
    verified = Verified(
        verifier="owner",
        verifier_kind="human",
        method="checked against the schedule and receipts",
        verified_on=date(2026, 11, 18),
        text_check=TextCheck.PASSED,
    )
    version = fixture_version(
        fixture_blocks(("50", "152.37"), (None, "201.11"), status=verified),
        status=verified,
        policy=fixture_policy(prepaid_kwh=HUNDREDTHS_UP, status=verified),
        billing=fixture_billing_policy(verified, PrepaidFixedCharges.NOT_FROM_PURCHASES),
    )
    purchase = calculate_purchase(
        version, date(2026, 7, 1), rand("10.00"), NOTHING_YET, fixture_vat_table(status=verified)
    )
    assert purchase.status is StatusKind.VERIFIED
    assert purchase.warnings == ()


# --------------------------------------------- several components, edges and precision


def test_segments_are_cut_at_the_thresholds_of_every_component() -> None:
    # Energy blocks at 50 and 350 kWh plus a network charge of 10c, then 20c above 100 kWh.
    # 40 kWh so far; R300.00; no fixed charges; half up.
    #   40-50:   (1.5237 + 0.10) x 1.125 = R1.8266625; 10 kWh cost 18.266625
    #   50-100:  (2.0111 + 0.10) x 1.125 = R2.3749875; 50 kWh cost 118.749375
    #   100-350: (2.0111 + 0.20) x 1.125 = R2.4874875; R162.984 left buys 65.5215... kWh
    #   total 60 + 65.5215... = 125.5215... -> 125.52 kWh
    network = fixture_blocks(("100", "10.00"), (None, "20.00"), name="network")
    version = tariff(BLOCKS, network, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(40))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("300.00"), so_far, VAT)
    assert [(s.from_kwh, s.to_kwh, s.price_per_kwh) for s in purchase.segments] == [
        (Decimal(40), Decimal(50), Decimal("1.8266625")),
        (Decimal(50), Decimal(100), Decimal("2.3749875")),
        (Decimal(100), Decimal(350), Decimal("2.4874875")),
    ]
    assert purchase.kwh == Decimal("125.52")
    middle = purchase.segments[1]
    rates = [s.citation.printed_text for s in middle.sources if s.role is SourceRole.RATE]
    uppers = [
        s.citation.printed_text for s in middle.sources if s.role is SourceRole.UPPER_THRESHOLD
    ]
    assert rates == ["201.11", "10.00"]  # each component's own block at 50-100 kWh
    assert uppers == ["350", "100"]


def test_a_purchase_starting_exactly_on_a_threshold_starts_in_the_next_block() -> None:
    # 50 kWh so far: R100.00 buys 100 / 2.2624875 = 44.199... -> 44.20 kWh, all in block 2.
    version = tariff(BLOCKS, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(50))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("100.00"), so_far, VAT)
    assert [s.from_kwh for s in purchase.segments] == [Decimal(50)]
    assert purchase.kwh == Decimal("44.20")


def test_a_purchase_that_exactly_fills_a_block_ends_on_its_threshold() -> None:
    # 30 kWh so far; R34.28325 is not a cent amount, so use a flat 100c tariff with a
    # block at 50: 20 kWh x R1.125 = R22.50 exactly fills it.
    version = tariff(fixture_blocks(("50", "100.00"), (None, "200.00")), billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(30))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("22.50"), so_far, VAT)
    assert purchase.kwh == Decimal(20)
    assert purchase.month_kwh_after == Decimal(50)
    assert [s.kwh for s in purchase.segments] == [Decimal(20)]


def test_a_purchase_on_a_seasons_first_day_uses_that_season() -> None:
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300.00")),
        fixture_season("low", (9, 1), (5, 31), (None, "200.00")),
    )
    version = tariff(seasonal, billing=NOT_FROM_PURCHASES)
    first_of_low = calculate_purchase(version, date(2026, 9, 1), rand("22.50"), NOTHING_YET, VAT)
    last_of_high = calculate_purchase(version, date(2026, 8, 31), rand("33.75"), NOTHING_YET, VAT)
    assert (first_of_low.kwh, last_of_high.kwh) == (Decimal("10.00"), Decimal("10.00"))


@pytest.mark.parametrize(
    ("day", "fixed"),
    [
        (date(2026, 12, 20), "34.88"),  # 31 days: 31.00 + VAT 3.875 -> 3.88
        (date(2027, 2, 10), "31.50"),  # 28 days: 28.00 + 3.50
        (date(2028, 2, 10), "32.63"),  # 29 days: 29.00 + 3.625 -> 3.63
    ],
)
def test_daily_charges_are_deducted_for_the_purchase_month(day: date, fixed: str) -> None:
    version = fixture_version(
        fixture_fixed("1.00", RateUnit.RAND_PER_DAY),
        BLOCKS,
        end=None,
        policy=fixture_policy(prepaid_kwh=HUNDREDTHS_UP),
    )
    purchase = calculate_purchase(version, day, rand("50.00"), NOTHING_YET, VAT)
    assert purchase.fixed_charges == rand(fixed)


@pytest.mark.parametrize("before", ["0.005", "30.001"])
def test_kwh_so_far_finer_than_the_prepaid_step_is_refused(before: str) -> None:
    # The reviewer's counterexample: 0.005 kWh so far would make the first segment
    # 0.995 kWh and let the rounding cross a threshold.
    version = tariff(BLOCKS, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(before))
    with pytest.raises(PrepaidPrecisionError):
        calculate_purchase(version, date(2026, 7, 10), rand("0.02"), so_far, VAT)


def test_a_threshold_finer_than_the_prepaid_step_is_refused() -> None:
    version = tariff(
        fixture_blocks(("50.005", "100.00"), (None, "200.00")), billing=NOT_FROM_PURCHASES
    )
    with pytest.raises(PrepaidPrecisionError):
        calculate_purchase(version, date(2026, 7, 10), rand("10.00"), NOTHING_YET, VAT)


def test_a_negative_amount_is_refused() -> None:
    version = tariff(BLOCKS, billing=NOT_FROM_PURCHASES)
    with pytest.raises(InvalidPurchaseError):
        calculate_purchase(version, date(2026, 7, 10), rand("-1.00"), NOTHING_YET, VAT)


def test_kwh_bought_with_no_earlier_purchase_is_refused() -> None:
    version = tariff(BLOCKS)
    with pytest.raises(InvalidPurchaseError):
        calculate_purchase(
            version, date(2026, 7, 10), rand("200.00"), MonthSoFar(purchases=0, kwh=Decimal(5)), VAT
        )


def test_fixed_charges_in_a_month_with_a_season_change_are_refused() -> None:
    # Seasons changing on 15 July: the first purchase's fixed charges are priced for the
    # whole month, which crosses the season boundary (documented refusal until P1-13's
    # splitting is used for prepaid fixed charges).
    seasonal = fixture_seasonal(
        fixture_season("a", (7, 15), (12, 31), (None, "100.00")),
        fixture_season("b", (1, 1), (7, 14), (None, "100.00")),
    )
    version = tariff(fixture_fixed("100.00"), seasonal)
    with pytest.raises(PeriodCrossesSeasonError):
        calculate_purchase(version, date(2026, 7, 20), rand("200.00"), NOTHING_YET, VAT)


def test_fixed_charges_in_a_month_with_a_vat_change_are_refused() -> None:
    table = VatTable(
        rates=(
            VatRate(
                start_cited=cited_date(date(2000, 1, 1)),
                end_cited=cited_date(date(2026, 7, 15)),
                percent=cited_decimal("12.5"),
            ),
            VatRate(
                start_cited=cited_date(date(2026, 7, 15)),
                end_cited=None,
                percent=cited_decimal("15"),
            ),
        )
    )
    version = tariff(fixture_fixed("100.00"), BLOCKS)
    with pytest.raises(VatRateChangesError):
        calculate_purchase(version, date(2026, 7, 20), rand("200.00"), NOTHING_YET, table)


@pytest.mark.parametrize("weak_part", ["label", "dates"])
def test_a_weaker_season_value_weakens_a_seasonal_purchase(weak_part: str) -> None:
    weak = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    base = fixture_season("high", (6, 1), (8, 31), (None, "300.00"))
    label = cited_label("high season", weak) if weak_part == "label" else base.label
    dates = base.dates
    if weak_part == "dates":
        dates = Cited[SeasonDates](
            value=base.dates.value, citation=base.dates.citation, status=weak
        )
    high = Season(name=base.name, label=label, dates=dates, blocks=base.blocks)
    low = fixture_season("low", (9, 1), (5, 31), (None, "200.00"))
    version = tariff(fixture_seasonal(high, low), billing=NOT_FROM_PURCHASES)
    july = calculate_purchase(version, date(2026, 7, 5), rand("33.75"), NOTHING_YET, VAT)
    october = calculate_purchase(version, date(2026, 10, 5), rand("33.75"), NOTHING_YET, VAT)
    assert july.status is StatusKind.USER_PROVIDED
    assert october.status is StatusKind.ESTIMATED
    roles = [source.role for source in july.segments[0].sources]
    assert SourceRole.SEASON in roles
    assert SourceRole.SEASON_LABEL in roles


def test_a_purchase_on_the_last_day_of_the_version_is_priced() -> None:
    version = tariff(fixture_flat("100.00"), billing=NOT_FROM_PURCHASES)  # to 1 July 2027
    purchase = calculate_purchase(version, date(2027, 6, 30), rand("11.25"), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal("10.00")


def test_fixed_charges_on_a_tariff_with_an_allocation_use_the_stated_eligibility() -> None:
    version = tariff(fixture_fixed("100.00"), fixture_flat("100.00"), fixture_free_basic("50"))
    purchases = calculate_month(
        version,
        [(date(2026, 7, 1), rand("123.75")), (date(2026, 7, 5), rand("11.25"))],
        VAT,
        free_basic_eligible=False,
    )
    assert [p.fixed_charges for p in purchases] == [rand("112.50"), Money.zero()]
    assert [p.kwh for p in purchases] == [Decimal("10.00"), Decimal("10.00")]


def test_a_weaker_header_or_vat_value_weakens_a_purchase() -> None:
    weak = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    version = fixture_version(
        fixture_flat("100.00"),
        policy=fixture_policy(prepaid_kwh=HUNDREDTHS_UP),
        billing=NOT_FROM_PURCHASES,
    )
    weak_header = version.model_validate(
        version.model_dump() | {"printed_name": cited_label("Fixture tariff", weak).model_dump()}
    )
    by_header = calculate_purchase(weak_header, date(2026, 7, 1), rand("11.25"), NOTHING_YET, VAT)
    by_vat = calculate_purchase(
        version, date(2026, 7, 1), rand("11.25"), NOTHING_YET, fixture_vat_table(status=weak)
    )
    assert by_header.status is StatusKind.USER_PROVIDED
    assert by_vat.status is StatusKind.USER_PROVIDED


def test_less_than_one_kwh_with_no_earlier_purchase_is_refused() -> None:
    with pytest.raises(InvalidPurchaseError):
        calculate_purchase(
            tariff(BLOCKS),
            date(2026, 7, 10),
            rand("200.00"),
            MonthSoFar(purchases=0, kwh=Decimal("0.5")),
            VAT,
        )


def test_a_monthly_levy_alone_is_a_fixed_charge_for_prepaid() -> None:
    # R20.00 a month (standard) + VAT 2.50 = R22.50 from the first purchase.
    levy = fixture_levy("20.00", RateUnit.RAND_PER_MONTH)
    version = tariff(fixture_flat("100.00"), levy)
    purchase = calculate_purchase(version, date(2026, 7, 1), rand("33.75"), NOTHING_YET, VAT)
    assert purchase.fixed_charges == rand("22.50")
    assert purchase.kwh == Decimal("10.00")


def test_nothing_spent_on_free_energy_buys_nothing() -> None:
    version = tariff(fixture_flat("0"), billing=NOT_FROM_PURCHASES)
    purchase = calculate_purchase(version, date(2026, 7, 1), Money.zero(), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal("0.00")


def test_the_open_last_block_cites_its_lower_threshold_only() -> None:
    version = tariff(BLOCKS, billing=NOT_FROM_PURCHASES)
    so_far = MonthSoFar(purchases=1, kwh=Decimal(400))
    purchase = calculate_purchase(version, date(2026, 7, 10), rand("10.00"), so_far, VAT)
    (segment,) = purchase.segments
    thresholds = [
        (s.role, s.citation.printed_text)
        for s in segment.sources
        if s.role in {SourceRole.LOWER_THRESHOLD, SourceRole.UPPER_THRESHOLD}
    ]
    assert thresholds == [(SourceRole.LOWER_THRESHOLD, "350")]


def test_nothing_spent_without_a_prepaid_point_buys_exactly_nothing() -> None:
    version = fixture_version(
        fixture_flat("100.00"), billing=NOT_FROM_PURCHASES, policy=fixture_policy()
    )
    purchase = calculate_purchase(version, date(2026, 7, 1), Money.zero(), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal(0)


def test_a_free_first_block_is_reached_even_with_nothing_spent() -> None:
    # kWh priced at zero cost nothing: R0.00 reaches the end of a free 50 kWh block (and a
    # later purchase starts from 50, so the block is not given twice).
    version = tariff(fixture_blocks(("50", "0"), (None, "200.00")), billing=NOT_FROM_PURCHASES)
    purchase = calculate_purchase(version, date(2026, 7, 1), Money.zero(), NOTHING_YET, VAT)
    assert purchase.kwh == Decimal(50)
    assert [(s.from_kwh, s.to_kwh, s.amount) for s in purchase.segments] == [
        (Decimal(0), Decimal(50), Money.zero())
    ]
    month = calculate_month(
        version, [(date(2026, 7, 1), Money.zero()), (date(2026, 7, 2), Money.zero())], VAT
    )
    assert [p.kwh for p in month] == [Decimal(50), Decimal("0.00")]
    assert month[1].month_kwh_before == Decimal(50)
