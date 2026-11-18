"""P1-13: period splitting (ADR-0011).

Fixture tariffs only (invented values, fixture VAT 12.5% unless a test builds its own
table; lines, VAT on the subtotal and the total to cents, half up; factors to millionths,
half up).
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    FreeBasicNotOfferedError,
    IncompatibleVersionsError,
    PeriodOutsideVersionError,
    PeriodTotal,
    WarningCode,
    calculate_bill,
    calculate_period,
)
from munisense.domain.citations import ProvidedBy, StatusKind, UserProvided, Verified
from munisense.domain.citations.model import TextCheck
from munisense.domain.money import InexactArithmeticError, Money, RateUnit, VatRate, VatTable
from munisense.domain.tariffs import (
    BillingPolicy,
    BlockReset,
    ConsumptionSplit,
    PrepaidFixedCharges,
    ProRating,
)
from support.builders import (
    cited_date,
    cited_decimal,
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
BASIC = fixture_fixed("213.45")
BLOCKS = fixture_blocks(("50", "152.37"), ("350", "201.11"), (None, "257.89"))
MID_JULY = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 15))
JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


def kwh(value: str) -> PeriodTotal:
    return PeriodTotal(kwh=Decimal(value))


# --------------------------------------------------------------- one month, no split


def test_a_whole_calendar_month_is_one_part_and_matches_calculate_bill() -> None:
    tariff = fixture_version(BASIC, BLOCKS)
    period_bill = calculate_period([tariff], JULY, kwh("412.3"), VAT)
    assert len(period_bill.parts) == 1
    assert period_bill.split is False
    assert period_bill.parts[0] == calculate_bill(tariff, JULY, kwh("412.3"), VAT)
    assert period_bill.total == rand("1185.35")
    codes = {warning.code for warning in period_bill.warnings}
    assert WarningCode.UNVERIFIED_BILLING_POLICY not in codes


# ------------------------------------------------------------ a reading period


def test_a_reading_period_across_two_months_is_split_and_pro_rated() -> None:
    # 15 July to 15 August 2026 (31 days), 412.3 kWh.
    # Factors (millionths, half up): 17/31 -> 0.548387 (July part), 14/31 -> 0.451613 (August).
    # kWh: 412.3 x 0.548387 = 226.0999601 in July; the rest, 186.2000399, in August.
    # July part: basic 213.45 x 0.548387 = 117.05320515 -> 117.05
    #   thresholds 50 and 350 x 0.548387 = 27.41935 and 191.93545
    #   27.41935 x 152.37c = 41.778863... -> 41.78; 164.5161 x 201.11c -> 330.86;
    #   34.1645101 x 257.89c -> 88.11; subtotal 577.80; VAT 72.225 -> 72.23; total 650.03
    # August part: basic 96.39679485 -> 96.40; 22.58065 x 152.37c -> 34.41;
    #   135.4839 x 201.11c -> 272.47; 28.1354899 x 257.89c -> 72.56;
    #   subtotal 475.84; VAT 59.48; total 535.32
    # Period total 650.03 + 535.32 = 1185.35 (the same as the whole of July at 412.3 kWh,
    # because sharing kWh and thresholds by the same fraction keeps the charge).
    bill = calculate_period([fixture_version(BASIC, BLOCKS)], MID_JULY, kwh("412.3"), VAT)
    july, august = bill.parts
    assert july.month_fraction == Decimal("0.548387")
    assert august.month_fraction == Decimal("0.451613")
    assert july.consumption_kwh == Decimal("226.0999601")
    assert august.consumption_kwh == Decimal("186.2000399")
    assert [line.amount for line in july.lines] == [
        rand("117.05"),
        rand("41.78"),
        rand("330.86"),
        rand("88.11"),
    ]
    assert (july.subtotal, july.vat, july.total) == (rand("577.80"), rand("72.23"), rand("650.03"))
    assert [line.amount for line in august.lines] == [
        rand("96.40"),
        rand("34.41"),
        rand("272.47"),
        rand("72.56"),
    ]
    assert august.total == rand("535.32")
    assert bill.total == rand("1185.35")
    assert bill.subtotal == rand("1053.64")
    assert bill.vat == rand("131.71")


def test_split_kwh_always_add_up_to_the_total() -> None:
    bill = calculate_period([fixture_version(BASIC, BLOCKS)], MID_JULY, kwh("412.3"), VAT)
    assert sum((part.consumption_kwh for part in bill.parts), Decimal(0)) == Decimal("412.3")


def test_a_pro_rated_block_names_its_scaled_thresholds() -> None:
    bill = calculate_period([fixture_version(BASIC, BLOCKS)], MID_JULY, kwh("412.3"), VAT)
    july = bill.parts[0]
    assert july.lines[1].description == "block 1: 0 to 27.419350 kWh"
    assert july.lines[0].description == ("17 days of the month, pro-rated: 0.548387 of a month")


def test_a_split_warns_about_an_unverified_billing_policy_only() -> None:
    estimated = calculate_period([fixture_version(BASIC, BLOCKS)], MID_JULY, kwh("10"), VAT)
    assert WarningCode.UNVERIFIED_BILLING_POLICY in {w.code for w in estimated.warnings}
    verified = Verified(
        verifier="owner",
        verifier_kind="human",
        method="checked against bills",
        verified_on=date(2026, 11, 18),
        text_check=TextCheck.PASSED,
    )
    tariff = fixture_version(BASIC, BLOCKS, billing=fixture_billing_policy(verified))
    trusted = calculate_period([tariff], MID_JULY, kwh("10"), VAT)
    assert WarningCode.UNVERIFIED_BILLING_POLICY not in {w.code for w in trusted.warnings}
    assert trusted.split is True


# ----------------------------------------------------------- other reasons to split


def test_a_version_change_inside_the_period_prices_each_side_with_its_version() -> None:
    # Old version to 1 July 2026 at 100c/kWh, new from 1 July at 120c/kWh; 15 June to
    # 15 July (30 days), 30 kWh, a daily charge of R1.00, no monthly values.
    # kWh: 16/30 -> 0.533333 -> 15.99999 kWh in June; 14.00001 in July.
    # June part: 16 days R16.00; 15.99999 x 100c = 15.99999 -> 16.00; subtotal 32.00;
    #   VAT 4.00; total 36.00
    # July part: 14 days R14.00; 14.00001 x 120c = 16.800012 -> 16.80; subtotal 30.80;
    #   VAT 3.85; total 34.65
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    old = fixture_version(
        daily, fixture_flat("100.00"), start=date(2025, 7, 1), end=date(2026, 7, 1)
    )
    new = fixture_version(daily, fixture_flat("120.00"), start=date(2026, 7, 1), end=None)
    period = BillingPeriod(start=date(2026, 6, 15), end=date(2026, 7, 15))
    bill = calculate_period([new, old], period, kwh("30"), VAT)
    june, july = bill.parts
    assert june.version_effective_from == date(2025, 7, 1)
    assert july.version_effective_from == date(2026, 7, 1)
    assert june.consumption_kwh == Decimal("15.99999")
    assert (june.total, july.total) == (rand("36.00"), rand("34.65"))
    assert bill.total == rand("70.65")


def test_a_season_change_inside_the_period_prices_each_season() -> None:
    # 15 August to 15 September 2026 (31 days), 31 kWh, daily charge only.
    # kWh: 17/31 -> 0.548387 -> 16.999997 in August (high, 300c); 14.000003 in September
    # (low, 200c). August: 17 x R1 = 17.00; 16.999997 x 3.00 = 50.999991 -> 51.00;
    # subtotal 68.00; VAT 8.50; total 76.50. September: 14.00; 28.000006 -> 28.00;
    # subtotal 42.00; VAT 5.25; total 47.25. Period 123.75.
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300.00")),
        fixture_season("low", (9, 1), (5, 31), (None, "200.00")),
    )
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    period = BillingPeriod(start=date(2026, 8, 15), end=date(2026, 9, 15))
    bill = calculate_period([fixture_version(daily, seasonal)], period, kwh("31"), VAT)
    august, september = bill.parts
    assert august.lines[1].description == "high season: all kWh"
    assert september.lines[1].description == "low season: all kWh"
    assert (august.total, september.total) == (rand("76.50"), rand("47.25"))
    assert bill.total == rand("123.75")


def test_a_vat_change_inside_the_period_splits_at_the_change() -> None:
    # VAT 12.5% until 1 August 2026, 15% from then. 15 July to 15 August, flat 100c/kWh,
    # 31 kWh, daily R1.00: July part 17.00 + 16.999997 -> 17.00 = 34.00, VAT 4.25 -> 38.25;
    # August part 14.00 + 14.000003 -> 14.00 = 28.00, VAT 15% = 4.20 -> 32.20; total 70.45.
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
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    bill = calculate_period(
        [fixture_version(daily, fixture_flat("100.00"))], MID_JULY, kwh("31"), table
    )
    assert [part.vat for part in bill.parts] == [rand("4.25"), rand("4.20")]
    assert bill.total == rand("70.45")


def test_a_small_use_within_the_allowance_is_free_in_every_part() -> None:
    # 15 July to 15 August, flat 100c/kWh, 50 free kWh a month, eligible, 20 kWh.
    # July part: 50 x 0.548387 = 27.41935 free; kWh 20 x 0.548387 = 10.96774, all free.
    bill = calculate_period(
        [fixture_version(fixture_flat("100.00"), fixture_free_basic("50"))],
        MID_JULY,
        kwh("20"),
        VAT,
        free_basic_eligible=True,
    )
    assert bill.total == Money.zero()


# ------------------------------------------------------------------------ refusals


def test_a_day_without_a_version_is_refused() -> None:
    old = fixture_version(BASIC, BLOCKS, start=date(2025, 7, 1), end=date(2026, 6, 20))
    new = fixture_version(BASIC, BLOCKS, start=date(2026, 7, 1), end=None)
    period = BillingPeriod(start=date(2026, 6, 15), end=date(2026, 7, 15))
    with pytest.raises(PeriodOutsideVersionError, match="2026-06-20"):
        calculate_period([old, new], period, kwh("10"), VAT)


@pytest.mark.parametrize("problem", ["none", "overlap", "other tariff"])
def test_versions_must_be_one_tariff_without_overlaps(problem: str) -> None:
    first = fixture_version(BASIC, BLOCKS, start=date(2025, 7, 1), end=date(2026, 7, 10))
    second = fixture_version(BASIC, BLOCKS, start=date(2026, 7, 1), end=None)
    versions = {
        "none": [],
        "overlap": [first, second],
        "other tariff": [
            fixture_version(BASIC, BLOCKS),
            fixture_version(BASIC, BLOCKS, start=date(2027, 7, 1), end=None, tariff_code="other"),
        ],
    }[problem]
    with pytest.raises(IncompatibleVersionsError):
        calculate_period(versions, MID_JULY, kwh("10"), VAT)


def test_without_a_pro_rating_point_a_non_terminating_factor_is_refused() -> None:
    tariff = fixture_version(BASIC, BLOCKS, policy=fixture_policy(pro_rating=None))
    with pytest.raises(InexactArithmeticError):
        calculate_period([tariff], MID_JULY, kwh("10"), VAT)


def test_a_season_starting_on_29_february_starts_on_1_march_in_other_years() -> None:
    # Seasons from 29 February and from 1 June. In 2027 (no 29 February) the first season
    # starts on 1 March, so 15 February to 15 March 2027 splits there, with no refusal.
    seasonal = fixture_seasonal(
        fixture_season("spring", (2, 29), (5, 31), (None, "300.00")),
        fixture_season("rest", (6, 1), (2, 28), (None, "200.00")),
    )
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    period = BillingPeriod(start=date(2027, 2, 15), end=date(2027, 3, 15))
    bill = calculate_period([fixture_version(daily, seasonal)], period, kwh("28"), VAT)
    assert [part.period.start for part in bill.parts] == [date(2027, 2, 15), date(2027, 3, 1)]
    assert [part.lines[1].description for part in bill.parts] == [
        "rest season: all kWh",
        "spring season: all kWh",
    ]


def test_a_billing_policy_that_claims_more_than_estimated_needs_evidence() -> None:
    claimed = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    with pytest.raises(ValidationError, match="evidence"):
        BillingPolicy(
            name="claimed",
            pro_rating=ProRating.BY_DAYS,
            consumption_split=ConsumptionSplit.BY_DAYS,
            block_reset=BlockReset.CALENDAR_MONTH,
            prepaid_fixed_charges=PrepaidFixedCharges.NOT_FROM_PURCHASES,
            status=claimed,
            evidence=(),
        )
    assert fixture_billing_policy(claimed).evidence  # with evidence it is accepted


# ----------------------------------------------------------- pro-rating every monthly value


def test_a_part_month_scales_the_free_allowance_against_blocks() -> None:
    # 15 July to 15 August, blocks 50 / 350 kWh, 50 free kWh a month, eligible, 60 kWh.
    # July: factor 0.548387; kWh 60 x 0.548387 = 32.90322; allowance 50 x 0.548387 =
    #   27.41935 (unscaled it would cover all 32.90322); threshold 27.41935.
    #   energy 27.41935 x 152.37c = 41.778... -> 41.78; 5.48387 x 201.11c = 11.028... -> 11.03
    #   credit 27.41935 kWh in block 1 -> -41.78; subtotal 11.03; VAT 1.37875 -> 1.38; 12.41
    # August: factor 0.451613; kWh 27.09678; allowance and threshold 22.58065
    #   energy 34.41 and 4.51613 x 201.11c = 9.0823... -> 9.08; credit -34.41
    #   subtotal 9.08; VAT 1.135 -> 1.14; total 10.22. Period 22.63.
    bill = calculate_period(
        [fixture_version(BLOCKS, fixture_free_basic("50"))],
        MID_JULY,
        kwh("60"),
        VAT,
        free_basic_eligible=True,
    )
    july, august = bill.parts
    assert [line.amount for line in july.lines] == [rand("41.78"), rand("11.03"), rand("-41.78")]
    assert july.lines[2].quantity == Decimal("27.419350")
    assert [line.amount for line in august.lines] == [rand("34.41"), rand("9.08"), rand("-34.41")]
    assert (july.total, august.total, bill.total) == (rand("12.41"), rand("10.22"), rand("22.63"))


def test_a_part_month_scales_a_monthly_levy() -> None:
    # 15 July to 15 August, flat 100c/kWh, levy R12.00 a month, 31 kWh.
    # July: 16.999997 kWh -> 17.00; levy 12 x 0.548387 = 6.580644 -> 6.58; subtotal 23.58;
    #   VAT 2.9475 -> 2.95; total 26.53. August: 14.00; levy 5.419356 -> 5.42; 19.42;
    #   VAT 2.4275 -> 2.43; total 21.85. Period 48.38.
    levy = fixture_levy("12.00", RateUnit.RAND_PER_MONTH)
    bill = calculate_period(
        [fixture_version(fixture_flat("100.00"), levy)], MID_JULY, kwh("31"), VAT
    )
    assert [part.lines[1].amount for part in bill.parts] == [rand("6.58"), rand("5.42")]
    assert bill.total == rand("48.38")


def test_a_part_month_scales_seasonal_block_thresholds() -> None:
    # High season blocks: 50 kWh at 100c, then 200c; 15 July to 15 August, 100 kWh.
    # July: 54.8387 kWh, threshold 27.41935: 27.42 + 27.41935 x 2.00 = 54.8387 -> 54.84;
    #   subtotal 82.26; VAT 10.2825 -> 10.28; total 92.54. August: 45.1613 kWh, threshold
    #   22.58065: 22.58 + 45.16; 67.74; VAT 8.4675 -> 8.47; total 76.21. Period 168.75.
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), ("50", "100.00"), (None, "200.00")),
        fixture_season("low", (9, 1), (5, 31), (None, "100.00")),
    )
    bill = calculate_period([fixture_version(seasonal)], MID_JULY, kwh("100"), VAT)
    july, august = bill.parts
    assert [line.amount for line in july.lines] == [rand("27.42"), rand("54.84")]
    assert [line.amount for line in august.lines] == [rand("22.58"), rand("45.16")]
    assert bill.total == rand("168.75")


def test_without_monthly_values_a_part_month_is_not_pro_rated() -> None:
    # A flat tariff with a daily charge: 3 to 10 July is priced as calculate_bill prices it,
    # with no month fraction, no split and no billing-policy warning, even with no
    # pro-rating point.
    tariff = fixture_version(
        fixture_fixed("1.00", RateUnit.RAND_PER_DAY),
        fixture_flat("100.00"),
        policy=fixture_policy(pro_rating=None),
    )
    period = BillingPeriod(start=date(2026, 7, 3), end=date(2026, 7, 10))
    bill = calculate_period([tariff], period, kwh("7"), VAT)
    assert bill.parts == (calculate_bill(tariff, period, kwh("7"), VAT),)
    assert bill.parts[0].month_fraction is None
    assert bill.split is False
    assert WarningCode.UNVERIFIED_BILLING_POLICY not in {w.code for w in bill.warnings}


@pytest.mark.parametrize(
    ("year", "fractions", "lines", "total"),
    [
        # 15 Feb to 15 Mar 2027 (28 days): February 14/28 = 0.5, March 14/31 = 0.451613
        # (the basic charge totals 0.951613 of a month: months differ in length).
        # kWh 412.3 x 14/28 = 206.15 each side.
        # Feb: basic 213.45 x 0.5 = 106.725 -> 106.73; thresholds 25, 175:
        #   25 x 152.37c = 38.0925 -> 38.09; 150 x 201.11c = 301.665 -> 301.67;
        #   31.15 x 257.89c = 80.3327... -> 80.33; subtotal 526.82; VAT 65.8525 -> 65.85;
        #   total 592.67
        # Mar: basic 96.39679485 -> 96.40; thresholds 22.58065, 158.06455: 34.41; 272.47;
        #   48.08545 x 257.89c = 124.007... -> 124.01; 527.29; VAT 65.91125 -> 65.91; 593.20
        (
            2027,
            [Decimal("0.500000"), Decimal("0.451613")],
            [["106.73", "38.09", "301.67", "80.33"], ["96.40", "34.41", "272.47", "124.01"]],
            "1185.87",
        ),
        # 15 Feb to 15 Mar 2028 (leap year, 29 days): February 15/29 = 0.517241, March
        # 0.451613; kWh 412.3 x 15/29 (0.517241) = 213.2584643 then 199.0415357.
        # Feb: 110.41; 39.41; 312.07; 83.10; subtotal 544.99; VAT 68.12375 -> 68.12; 613.11
        # Mar: 96.40; 34.41; 272.47; 105.68; 508.96; VAT 63.62; 572.58. Period 1185.69.
        (
            2028,
            [Decimal("0.517241"), Decimal("0.451613")],
            [["110.41", "39.41", "312.07", "83.10"], ["96.40", "34.41", "272.47", "105.68"]],
            "1185.69",
        ),
    ],
)
def test_months_of_different_lengths_are_pro_rated_by_their_own_days(
    year: int, fractions: list[Decimal], lines: list[list[str]], total: str
) -> None:
    period = BillingPeriod(start=date(year, 2, 15), end=date(year, 3, 15))
    tariff = fixture_version(BASIC, BLOCKS, start=date(2026, 7, 1), end=None)
    bill = calculate_period([tariff], period, kwh("412.3"), VAT)
    assert [part.month_fraction for part in bill.parts] == fractions
    assert [[line.amount for line in part.lines] for part in bill.parts] == [
        [rand(amount) for amount in amounts] for amounts in lines
    ]
    assert bill.total == rand(total)


def test_a_season_starting_on_29_february_cuts_on_29_february_in_a_leap_year() -> None:
    seasonal = fixture_seasonal(
        fixture_season("spring", (2, 29), (5, 31), (None, "300.00")),
        fixture_season("rest", (6, 1), (2, 28), (None, "200.00")),
    )
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    period = BillingPeriod(start=date(2028, 2, 15), end=date(2028, 3, 15))
    tariff = fixture_version(daily, seasonal, end=None)
    bill = calculate_period([tariff], period, kwh("29"), VAT)
    assert [part.period.start for part in bill.parts] == [
        date(2028, 2, 15),
        date(2028, 2, 29),
        date(2028, 3, 1),
    ]


def test_an_open_ended_version_that_is_not_the_last_overlaps() -> None:
    first = fixture_version(BASIC, BLOCKS, start=date(2025, 7, 1), end=None)
    second = fixture_version(BASIC, BLOCKS, start=date(2026, 7, 1), end=None)
    with pytest.raises(IncompatibleVersionsError):
        calculate_period([first, second], MID_JULY, kwh("10"), VAT)


def test_season_starts_cut_only_the_days_of_their_own_version() -> None:
    # The old version is flat; the new one (from 1 September) is seasonal with a season
    # starting 15 August. That start falls in the old version's days, so it must not cut.
    seasonal = fixture_seasonal(
        fixture_season("a", (8, 15), (12, 31), (None, "100.00")),
        fixture_season("b", (1, 1), (8, 14), (None, "100.00")),
    )
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    old = fixture_version(
        daily, fixture_flat("100.00"), start=date(2025, 7, 1), end=date(2026, 9, 1)
    )
    new = fixture_version(daily, seasonal, start=date(2026, 9, 1), end=None)
    period = BillingPeriod(start=date(2026, 8, 1), end=date(2026, 9, 10))
    bill = calculate_period([old, new], period, kwh("10"), VAT)
    assert [part.period.start for part in bill.parts] == [date(2026, 8, 1), date(2026, 9, 1)]


def test_a_period_ending_in_the_last_month_of_the_calendar_is_split_without_error() -> None:
    period = BillingPeriod(start=date(9999, 12, 1), end=date(9999, 12, 31))
    tariff = fixture_version(fixture_flat("100.00"), start=date(9999, 1, 1), end=None)
    bill = calculate_period([tariff], period, kwh("1"), fixture_vat_table())
    assert len(bill.parts) == 1


def test_parts_from_versions_with_different_policies_keep_every_warning() -> None:
    # Two estimated rounding policies with different names: each part warns about its own,
    # and the period keeps both warnings and names both policies.
    daily = fixture_fixed("1.00", RateUnit.RAND_PER_DAY)
    old = fixture_version(
        daily,
        fixture_flat("100.00"),
        start=date(2025, 7, 1),
        end=date(2026, 7, 1),
        policy=fixture_policy(name="old-rounding"),
    )
    new = fixture_version(daily, fixture_flat("100.00"), start=date(2026, 7, 1), end=None)
    period = BillingPeriod(start=date(2026, 6, 15), end=date(2026, 7, 15))
    bill = calculate_period([old, new], period, kwh("10"), VAT)
    assert bill.rounding_policies == ("old-rounding", "fixture")
    assert bill.rounding_policy_status is StatusKind.ESTIMATED
    rounding_warnings = [
        w.message for w in bill.warnings if w.code is WarningCode.UNVERIFIED_ROUNDING_POLICY
    ]
    assert len(rounding_warnings) == 2
    assert any("'old-rounding'" in message for message in rounding_warnings)
    assert any("'fixture'" in message for message in rounding_warnings)


def test_eligibility_must_suit_every_version_in_the_period() -> None:
    # The old version offers a free allocation, the new one does not: an eligible customer
    # is refused for the new part, so the whole period is refused (documented behaviour).
    old = fixture_version(
        fixture_flat("100.00"),
        fixture_free_basic("50"),
        start=date(2025, 7, 1),
        end=date(2026, 7, 1),
    )
    new = fixture_version(fixture_flat("100.00"), start=date(2026, 7, 1), end=None)
    period = BillingPeriod(start=date(2026, 6, 1), end=date(2026, 8, 1))
    with pytest.raises(FreeBasicNotOfferedError):
        calculate_period([old, new], period, kwh("10"), VAT, free_basic_eligible=True)


def test_a_version_outside_the_period_is_ignored() -> None:
    older = fixture_version(BASIC, BLOCKS, start=date(2024, 7, 1), end=date(2025, 7, 1))
    current = fixture_version(BASIC, BLOCKS, start=date(2025, 7, 1), end=None)
    bill = calculate_period([older, current], JULY, kwh("412.3"), VAT)
    assert bill.total == rand("1185.35")
    assert bill.parts[0].version_effective_from == date(2025, 7, 1)


def test_a_scaled_allowance_spanning_two_scaled_blocks_credits_each_block() -> None:
    # 15 July to 15 August, blocks 50 / 350 kWh, 60 free kWh a month, eligible, 100 kWh.
    # July: kWh 54.8387; allowance 60 x 0.548387 = 32.90322; threshold 27.41935, so the
    #   credit spans two blocks: 27.41935 x 152.37c -> -41.78 and 5.48387 x 201.11c =
    #   11.0286... -> -11.03 (with unscaled thresholds it would be one -50.13 credit).
    #   energy 41.78 + 55.14; subtotal 44.11; VAT 5.51375 -> 5.51; total 49.62
    # August: kWh 45.1613; allowance 27.09678; credits -34.41 and 4.51613 x 201.11c ->
    #   -9.08; energy 34.41 + 45.41; subtotal 36.33; VAT 4.54125 -> 4.54; total 40.87.
    # Period 90.49.
    bill = calculate_period(
        [fixture_version(BLOCKS, fixture_free_basic("60"))],
        MID_JULY,
        kwh("100"),
        VAT,
        free_basic_eligible=True,
    )
    july, august = bill.parts
    july_credits = [line.amount for line in july.lines if line.component == "free_basic"]
    august_credits = [line.amount for line in august.lines if line.component == "free_basic"]
    assert july_credits == [rand("-41.78"), rand("-11.03")]
    assert august_credits == [rand("-34.41"), rand("-9.08")]
    assert (july.total, august.total, bill.total) == (rand("49.62"), rand("40.87"), rand("90.49"))
