"""P1-9: City of Ekurhuleni Tariff B (Residential), 2026/27, end to end.

The Ekurhuleni example tariff for P1 (E32; not the owner's meter, E34), transcribed from
the signed schedule in `data/sources/ekurhuleni/` into the drafts
`data/drafts/ekurhuleni/2026-27/` (not reviewed or published; P3), with the VAT rate from
SARS (`data/sources/sars/`, `data/drafts/vat/`). Every value is `estimated` (E29) until
the citation check (P2) and a human check exist.

Hand calculations use only the printed values:

- basic charge R109.78 (1-phase, R1.1) or R203.89 (3-phase, R1.2) per month, page 4
- energy R3.37,00 per kWh, read as R3.3700, both seasons (R.3, R.4), page 4
- VAT 15%, VAT 404 guide page 15; prices exclude VAT, schedule page 1
- rounding (estimated): lines to cents half up, VAT once on the subtotal to cents half up
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from munisense.domain.billing import (
    BillingPeriod,
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
    PeriodTotal,
    SourceRole,
    WarningCode,
    calculate_bill,
    calculate_month,
    calculate_period,
)
from munisense.domain.citations import Estimated, StatusKind, cited_statuses
from munisense.domain.money import Money, VatTable
from munisense.domain.tariffs import FixedCharge, SeasonalEnergy, TariffVersion

ROOT = Path(__file__).resolve().parents[3]
DRAFTS = ROOT / "data" / "drafts"
TARIFFS = DRAFTS / "ekurhuleni" / "2026-27"
SCHEDULE_SHA = "db55c0d359b41469d766c6196c51b59cbfe469a139b334f9c87195a92dc07e73"
VAT_GUIDE_SHA = "9204c3f8d0cea0200b84559f19bfa638d2f6eb6e2083ac633da4938eec52c31a"
VAT_ACT_SHA = "5f6e4225703d6ba2f0d19bd0911fe580f787bcab4d1f8d6f421525051366ad1e"
E29_REASON = "citation check not built until P2"


def tariff(phase: str) -> TariffVersion:
    path = TARIFFS / f"tariff-b-residential-{phase}.json"
    return TariffVersion.model_validate_json(path.read_text(encoding="utf-8"))


def vat_table() -> VatTable:
    path = DRAFTS / "vat" / "south-africa.json"
    return VatTable.model_validate_json(path.read_text(encoding="utf-8"))


def month(year: int, number: int) -> BillingPeriod:
    end = date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1)
    return BillingPeriod(start=date(year, number, 1), end=end)


def rand(value: str) -> Money:
    return Money(rand=Decimal(value))


# ---------------------------------------------------------------- the data itself


def _committed_sources() -> set[str]:
    return {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data" / "sources").rglob("*.pdf")
    }


def _cited_documents(data: object) -> set[str]:
    """The document of every cited value ({"value", "citation", "status"}) in dumped JSON."""
    found: set[str] = set()
    if isinstance(data, dict):
        if {"value", "citation", "status"} <= data.keys():
            found.add(data["citation"]["document_sha256"])
        for item in data.values():
            found |= _cited_documents(item)
    elif isinstance(data, list):
        for item in data:
            found |= _cited_documents(item)
    return found


@pytest.mark.parametrize("phase", ["1-phase", "3-phase"])
def test_every_value_cites_a_committed_source_document(phase: str) -> None:
    cited = _cited_documents(tariff(phase).model_dump(mode="json"))
    assert cited == {SCHEDULE_SHA}
    assert cited <= _committed_sources()


def test_the_vat_rate_cites_a_committed_source_document() -> None:
    table = vat_table()
    assert _cited_documents(table.model_dump(mode="json")) == {VAT_GUIDE_SHA}
    assert VAT_GUIDE_SHA in _committed_sources()
    # The Act that stopped the 2025 increase is named (in full) in the status reason.
    reason = table.rates[0].percent.status
    assert isinstance(reason, Estimated)
    assert VAT_ACT_SHA in reason.reason
    assert VAT_ACT_SHA in _committed_sources()


@pytest.mark.parametrize("phase", ["1-phase", "3-phase"])
def test_every_value_is_estimated_with_the_agreed_reason(phase: str) -> None:
    statuses = cited_statuses(tariff(phase)) + cited_statuses(vat_table())
    assert statuses
    for status in statuses:
        assert isinstance(status, Estimated)
        assert status.reason.startswith(E29_REASON)
    policy = tariff(phase).rounding_policy.status
    assert isinstance(policy, Estimated)
    assert "not in the schedule" in policy.reason


def test_the_transcribed_values_are_the_printed_ones() -> None:
    for phase, basic in (("1-phase", "109.78"), ("3-phase", "203.89")):
        fixed, energy = tariff(phase).components
        assert isinstance(fixed, FixedCharge)
        assert isinstance(energy, SeasonalEnergy)
        assert fixed.rate.value.value == Decimal(basic)
        assert fixed.rate.citation.printed_text == f"R{basic}"
        high, low = energy.seasons
        for season, expected in ((high, (6, 1, 8, 31)), (low, (9, 1, 5, 31))):
            dates = season.dates.value
            assert (dates.start_month, dates.start_day, dates.end_month, dates.end_day) == expected
        assert high.dates.citation.printed_text.startswith("R.3. High Demand Season")
        assert low.dates.citation.printed_text.startswith("R.4. Low Demand Season")
        for season in (high, low):
            (block,) = season.blocks
            assert block.up_to_kwh is None
            assert block.rate.value.value == Decimal("3.3700")
            assert block.rate.citation.printed_text == "R3.37,00"
            assert block.rate.citation.page == 4
    one = tariff("1-phase")
    assert vat_table().rates[0].percent.value == Decimal(15)
    assert vat_table().rates[0].start == date(2018, 4, 1)
    assert vat_table().rates[0].end is None
    assert one.effective_from.value == date(2026, 7, 1)
    assert one.effective_to is not None
    assert one.effective_to.value == date(2027, 7, 1)  # printed "30 JUNE 2027", inclusive


# ------------------------------------------------------------- hand-checked bills


@pytest.mark.parametrize(
    ("phase", "period", "kwh", "lines", "subtotal", "vat", "total"),
    [
        # July 2026 (high-demand season), nothing used:
        #   basic 109.78; subtotal 109.78; VAT 15% = 16.467 -> 16.47; total 126.25
        ("1-phase", month(2026, 7), "0", ["109.78"], "109.78", "16.47", "126.25"),
        # July 2026, 350 kWh:
        #   energy 350 x 3.3700 = 1179.50; subtotal 109.78 + 1179.50 = 1289.28
        #   VAT 15% = 193.392 -> 193.39; total 1482.67
        ("1-phase", month(2026, 7), "350", ["109.78", "1179.50"], "1289.28", "193.39", "1482.67"),
        # February 2027 (low-demand season, 28 days; the basic charge is per month):
        #   energy 123.45 x 3.3700 = 416.0265 -> 416.03; subtotal 525.81
        #   VAT 15% = 78.8715 -> 78.87; total 604.68
        ("1-phase", month(2027, 2), "123.45", ["109.78", "416.03"], "525.81", "78.87", "604.68"),
        # January 2027 (low-demand season), 3-phase, 812.4 kWh:
        #   basic 203.89; energy 812.4 x 3.3700 = 2737.788 -> 2737.79; subtotal 2941.68
        #   VAT 15% = 441.252 -> 441.25; total 3382.93
        ("3-phase", month(2027, 1), "812.4", ["203.89", "2737.79"], "2941.68", "441.25", "3382.93"),
        # June 2027 (high-demand season, last month of the version), 50.5 kWh; the energy
        # line is an exact half (half-even would give 170.18); VAT is not a tie:
        #   energy 50.5 x 3.3700 = 170.185 -> 170.19; subtotal 279.97
        #   VAT 15% = 41.9955 -> 42.00; total 321.97
        ("1-phase", month(2027, 6), "50.5", ["109.78", "170.19"], "279.97", "42.00", "321.97"),
        # October 2026 (low-demand season), 101.4 kWh; VAT is an exact half with an even
        # cent digit, so half up and half even differ (half even would give 67.72):
        #   energy 101.4 x 3.3700 = 341.718 -> 341.72; subtotal 109.78 + 341.72 = 451.50
        #   VAT 15% = 67.725 -> 67.73; total 519.23
        ("1-phase", month(2026, 10), "101.4", ["109.78", "341.72"], "451.50", "67.73", "519.23"),
    ],
)
def test_tariff_b_bills_are_reproduced_to_the_cent(  # one row of the table
    phase: str,
    period: BillingPeriod,
    kwh: str,
    lines: list[str],
    subtotal: str,
    vat: str,
    total: str,
) -> None:
    bill = calculate_bill(tariff(phase), period, PeriodTotal(kwh=Decimal(kwh)), vat_table())
    assert [line.amount for line in bill.lines] == [rand(amount) for amount in lines]
    assert bill.subtotal == rand(subtotal)
    assert bill.vat == rand(vat)
    assert bill.total == rand(total)


HIGH, LOW = "R.3. High Demand Season", "R.4. Low Demand Season"


@pytest.mark.parametrize(
    ("period", "season"),
    [
        # every bill month above, and the months whose exclusive end is the next season's
        # first day (August, May)
        (month(2026, 7), HIGH),
        (month(2026, 8), HIGH),
        (month(2026, 10), LOW),
        (month(2027, 1), LOW),
        (month(2027, 2), LOW),
        (month(2027, 5), LOW),
        (month(2027, 6), HIGH),
    ],
)
def test_each_month_is_priced_from_its_own_season(period: BillingPeriod, season: str) -> None:
    bill = calculate_bill(tariff("1-phase"), period, PeriodTotal(kwh=Decimal(10)), vat_table())
    energy = bill.lines[1]
    cited = [s.citation.printed_text for s in energy.sources if s.role is SourceRole.SEASON]
    assert len(cited) == 1
    assert cited[0].startswith(season)


def test_a_bill_names_its_sources_and_warns_that_nothing_is_verified() -> None:
    bill = calculate_bill(
        tariff("1-phase"), month(2026, 7), PeriodTotal(kwh=Decimal(350)), vat_table()
    )
    assert bill.tariff_name == "TARIFF B (RESIDENTIAL)"
    assert bill.status is StatusKind.ESTIMATED
    assert bill.rounding_policy == "ekurhuleni-estimated"
    assert {warning.code.value for warning in bill.warnings} == {
        "unverified_values",
        "unverified_rounding_policy",
    }
    energy = bill.lines[1]
    rate_source = next(s for s in energy.sources if s.role is SourceRole.RATE)
    assert rate_source.citation.document_sha256 == SCHEDULE_SHA
    assert rate_source.citation.page == 4
    assert rate_source.citation.printed_text == "R3.37,00"
    assert bill.vat_rate.percent.citation.document_sha256 == VAT_GUIDE_SHA


# ------------------------------------------------------------------------ refusals


def test_a_period_after_the_2026_27_year_is_refused() -> None:
    with pytest.raises(PeriodOutsideVersionError):
        calculate_bill(tariff("1-phase"), month(2027, 7), PeriodTotal(kwh=Decimal(1)), vat_table())


def test_a_period_before_the_2026_27_year_is_refused() -> None:
    with pytest.raises(PeriodOutsideVersionError):
        calculate_bill(tariff("1-phase"), month(2026, 6), PeriodTotal(kwh=Decimal(1)), vat_table())


def test_calculate_bill_refuses_a_part_month_which_calculate_period_splits() -> None:
    period = BillingPeriod(start=date(2026, 8, 15), end=date(2026, 9, 15))
    with pytest.raises(NonMonthlyPeriodError):
        calculate_bill(tariff("1-phase"), period, PeriodTotal(kwh=Decimal(1)), vat_table())


def test_a_reading_period_across_two_months_is_split_and_pro_rated() -> None:
    # 15 July to 15 August 2026 (31 days), 1-phase, 300 kWh; billing policy and pro-rating
    # point estimated (by days; factors to millionths, half up).
    # Factors 17/31 -> 0.548387 and 14/31 -> 0.451613; kWh 164.5161 and 135.4839.
    # July part: basic 109.78 x 0.548387 = 60.20192486 -> 60.20;
    #   energy 164.5161 x 3.3700 = 554.419257 -> 554.42; subtotal 614.62;
    #   VAT 15% = 92.193 -> 92.19; total 706.81
    # August part: basic 49.57807514 -> 49.58; energy 135.4839 x 3.3700 = 456.580743
    #   -> 456.58; subtotal 506.16; VAT 75.924 -> 75.92; total 582.08
    # Period total 1288.89
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 15))
    bill = calculate_period([tariff("1-phase")], period, PeriodTotal(kwh=Decimal(300)), vat_table())
    july, august = bill.parts
    assert [line.amount for line in july.lines] == [rand("60.20"), rand("554.42")]
    assert july.total == rand("706.81")
    assert [line.amount for line in august.lines] == [rand("49.58"), rand("456.58")]
    assert august.total == rand("582.08")
    assert bill.total == rand("1288.89")
    assert bill.billing_policies == ("ekurhuleni-estimated",)
    assert WarningCode.UNVERIFIED_BILLING_POLICY in {w.code for w in bill.warnings}


def test_a_period_starting_before_2026_27_is_refused_without_the_old_schedule() -> None:
    # The 2025/26 schedule is not transcribed, so the cross-over from 1 July 2026, which
    # the schedule says is billed pro rata, cannot be priced yet.
    period = BillingPeriod(start=date(2026, 6, 15), end=date(2026, 7, 15))
    with pytest.raises(PeriodOutsideVersionError):
        calculate_period([tariff("1-phase")], period, PeriodTotal(kwh=Decimal(1)), vat_table())


# ---------------------------------------------------- prepaid purchases, from P1-15
# The estimated billing policy takes the month's basic charge, with VAT, from the first
# purchase; blocks reset monthly (Tariff B has none); kWh rounded once per purchase to
# hundredths, half up. One kWh costs R3.3700 x 1.15 = R3.8755 in both seasons.
# A cent amount can only buy kWh with an exact third decimal when the kWh are whole
# (R3.8755 x n/1000 is a whole number of cents only when n is a multiple of 20,000), so no
# Ekurhuleni purchase lands on a half-hundredth: the rounding mode is proven by fixtures.


def test_a_month_of_prepaid_purchases_on_tariff_b_1_phase() -> None:
    # 1 July 2026 R500.00: basic 109.78 + VAT 16.467 -> 16.47 = R126.25 deducted;
    #   R373.75 / 3.8755 = 96.4391... -> 96.44 kWh
    # 15 July 2026 R300.00: nothing deducted; 300 / 3.8755 = 77.4093... -> 77.41 kWh
    # Month: 173.85 kWh
    purchases = calculate_month(
        tariff("1-phase"),
        [(date(2026, 7, 1), rand("500.00")), (date(2026, 7, 15), rand("300.00"))],
        vat_table(),
    )
    assert [p.fixed_charges for p in purchases] == [rand("126.25"), Money.zero()]
    assert [p.kwh for p in purchases] == [Decimal("96.44"), Decimal("77.41")]
    assert purchases[-1].month_kwh_after == Decimal("173.85")
    assert purchases[0].segments[0].price_per_kwh == Decimal("3.875500")
    codes = {w.code for w in purchases[0].warnings}
    assert {WarningCode.UNVERIFIED_ROUNDING_POLICY, WarningCode.UNVERIFIED_BILLING_POLICY} <= codes


def test_a_month_of_prepaid_purchases_on_tariff_b_3_phase_in_the_low_season() -> None:
    # 2 October 2026 R1,000.00: basic 203.89 + VAT 30.5835 -> 30.58 = R234.47 deducted;
    #   R765.53 / 3.8755 = 197.5306... -> 197.53 kWh (low-demand season, R.4)
    # 20 October 2026 R250.00: 250 / 3.8755 = 64.5077... -> 64.51 kWh
    purchases = calculate_month(
        tariff("3-phase"),
        [(date(2026, 10, 2), rand("1000.00")), (date(2026, 10, 20), rand("250.00"))],
        vat_table(),
    )
    assert purchases[0].fixed_charges == rand("234.47")
    assert [p.kwh for p in purchases] == [Decimal("197.53"), Decimal("64.51")]
    sources = purchases[0].segments[0].sources
    assert [x.citation.printed_text for x in sources if x.role is SourceRole.RATE] == ["R3.37,00"]
    season = [x.citation.printed_text for x in sources if x.role is SourceRole.SEASON]
    assert len(season) == 1
    assert season[0].startswith("R.4. Low Demand Season")
