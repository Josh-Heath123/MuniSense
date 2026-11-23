"""The export credit (P4-8, ADR-0016 point 6). Values are fixtures.

Fixture energy rates (cents per kWh), high season: peak 500, standard 200, off-peak 100.
Fixture export credit rates, high season: peak 400, standard 150, off-peak 80. VAT 12.5%.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.billing import (
    Bill,
    BillingPeriod,
    NegativeBillError,
    NonMonthlyPeriodError,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    calculate_bill,
    calculate_period,
)
from munisense.domain.citations import TextCheck, Verified
from munisense.domain.tariffs import (
    Component,
    ExportCap,
    TariffVersion,
    TouPeriod,
    VatTreatment,
)
from support.builders import (
    FIXTURE_EXPORT_CENTS,
    fixture_billing_policy,
    fixture_calendar,
    fixture_export_credit,
    fixture_flat,
    fixture_tou_energy,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
CALENDAR = fixture_calendar()
CAP = fixture_billing_policy(export_cap=ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH)
JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
PEAK, STANDARD, OFF_PEAK = TouPeriod.PEAK, TouPeriod.STANDARD, TouPeriod.OFF_PEAK


def version(*components: Component) -> TariffVersion:
    return fixture_version(
        fixture_tou_energy(),
        *(components or (fixture_export_credit(),)),
        tou_calendar=CALENDAR,
        billing=CAP,
    )


def profile(used: tuple[str, str, str], exported: dict[TouPeriod, str]) -> TimeOfUseBuckets:
    return TimeOfUseBuckets(
        used_kwh=dict(zip((PEAK, STANDARD, OFF_PEAK), map(Decimal, used), strict=True)),
        exported_kwh={p: Decimal(v) for p, v in exported.items()},
    )


def amounts(bill: Bill) -> dict[str, str]:
    return {line.description: str(line.amount.rand) for line in bill.lines}


def test_exports_are_credited_up_to_the_use_in_the_same_period() -> None:
    """Used 100 / 200 / 300 kWh: energy R500 + R400 + R300 = R1,200.00.
    Exported 50 kWh at peak (all credited: 50 x R4.00 = R200.00) and 400 kWh off-peak
    (capped at the 300 kWh used: 300 x R0.80 = R240.00). Subtotal R760.00, VAT 12.5%
    R95.00, total R855.00."""
    bill = calculate_bill(
        version(), JULY, profile(("100", "200", "300"), {PEAK: "50", OFF_PEAK: "400"}), VAT
    )
    assert amounts(bill) == {
        "high demand season: peak kWh": "500.00",
        "high demand season: standard kWh": "400.00",
        "high demand season: off-peak kWh": "300.00",
        "high demand season: peak kWh exported, credited": "-200.00",
        "high demand season: off-peak kWh exported, credited": "-240.00",
    }
    credited = {line.description: line.quantity for line in bill.lines if line.amount.rand < 0}
    assert credited["high demand season: off-peak kWh exported, credited"] == Decimal(300)
    assert (bill.subtotal.rand, bill.vat.rand, bill.total.rand) == (
        Decimal("760.00"),
        Decimal("95.00"),
        Decimal("855.00"),
    )


def test_zero_export_gives_the_bill_without_a_credit() -> None:
    with_zero = calculate_bill(
        version(), JULY, profile(("100", "200", "300"), {PEAK: "0", OFF_PEAK: "0"}), VAT
    )
    without = calculate_bill(
        fixture_version(fixture_tou_energy(), tou_calendar=CALENDAR),
        JULY,
        profile(("100", "200", "300"), {}),
        VAT,
    )
    assert with_zero.lines == without.lines
    assert with_zero.total == without.total


def test_a_zero_rated_credit_carries_no_vat() -> None:
    """VAT 12.5% on the R1,200.00 of energy only: R150.00; total R1,200 - R200 + R150."""
    credit = fixture_export_credit(vat=VatTreatment.ZERO_RATED)
    bill = calculate_bill(version(credit), JULY, profile(("100", "200", "300"), {PEAK: "50"}), VAT)
    assert bill.vat.rand == Decimal("150.00")
    assert bill.total.rand == Decimal("1150.00")


def test_exports_on_a_tariff_without_an_export_credit_are_refused() -> None:
    plain = fixture_version(fixture_tou_energy(), tou_calendar=CALENDAR)
    with pytest.raises(UnsupportedConsumptionError, match="no export credit"):
        calculate_bill(plain, JULY, profile(("1", "1", "1"), {PEAK: "0"}), VAT)


def test_an_export_credit_needs_the_billing_policys_export_cap() -> None:
    with pytest.raises(ValidationError, match="needs its billing policy's export cap"):
        fixture_version(fixture_tou_energy(), fixture_export_credit(), tou_calendar=CALENDAR)


def test_an_export_credit_needs_a_rate_for_every_period_of_every_season() -> None:
    cents = {k: v for k, v in FIXTURE_EXPORT_CENTS.items() if k != ("low", OFF_PEAK)}
    with pytest.raises(ValidationError, match="no rate for off_peak in the season 'low'"):
        version(fixture_export_credit(cents))


def test_a_part_month_with_exports_is_refused() -> None:
    """The cap is per calendar month: a part of a month cannot be credited until a source
    says how."""
    half = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 16))
    with pytest.raises(NonMonthlyPeriodError, match="whole calendar months"):
        calculate_bill(version(), half, profile(("1", "1", "1"), {PEAK: "1"}), VAT)
    assert calculate_bill(version(), half, profile(("1", "1", "1"), {PEAK: "0"}), VAT)


def test_a_credit_that_would_make_the_bill_negative_is_refused() -> None:
    """Credit rates above the energy rates (made up): 100 kWh at peak, all exported:
    R500.00 - R1,000.00 would be negative."""
    generous = fixture_export_credit(dict.fromkeys(FIXTURE_EXPORT_CENTS, "1000"))
    with pytest.raises(NegativeBillError, match="negative"):
        calculate_bill(version(generous), JULY, profile(("100", "0", "0"), {PEAK: "100"}), VAT)


def test_exports_over_more_than_one_calendar_month_are_refused() -> None:
    """Shared-out figures cannot show each month's use, so the monthly cap could not be
    applied (July exports 100 and uses none, August uses 100: the real credit is 0)."""
    both = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 9, 1))
    with pytest.raises(NonMonthlyPeriodError, match="only on a bill of one calendar month"):
        calculate_period([version()], both, profile(("200", "0", "0"), {PEAK: "300"}), VAT)
    assert calculate_period([version()], both, profile(("200", "0", "0"), {PEAK: "0"}), VAT)


def test_one_whole_month_through_calculate_period_is_credited() -> None:
    bill = calculate_period([version()], JULY, profile(("100", "0", "0"), {PEAK: "50"}), VAT)
    credit = next(line for line in bill.parts[0].lines if line.amount.rand < 0)
    assert (credit.quantity, credit.amount.rand) == (Decimal(50), Decimal("-200.00"))


VERIFIED = Verified(
    verifier="owner",
    verifier_kind="human",
    method="fixture",
    verified_on=date(2026, 1, 1),
    text_check=TextCheck.PASSED,
)


def test_a_credit_under_an_unverified_policy_warns() -> None:
    """The export cap's reading is the billing policy's; until that is verified, every bill
    with a credit says so, whatever the status of the rates."""
    bill = calculate_bill(version(), JULY, profile(("100", "0", "0"), {PEAK: "50"}), VAT)
    assert "unverified_export_cap" in {w.code for w in bill.warnings}
    verified_policy = fixture_billing_policy(
        status=VERIFIED, export_cap=ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH
    )
    trusted = fixture_version(
        fixture_tou_energy(),
        fixture_export_credit(),
        tou_calendar=CALENDAR,
        billing=verified_policy,
    )
    bill = calculate_bill(trusted, JULY, profile(("100", "0", "0"), {PEAK: "50"}), VAT)
    assert "unverified_export_cap" not in {w.code for w in bill.warnings}
    no_credit = calculate_bill(version(), JULY, profile(("100", "0", "0"), {}), VAT)
    assert "unverified_export_cap" not in {w.code for w in no_credit.warnings}


def test_a_version_has_at_most_one_export_credit() -> None:
    with pytest.raises(ValidationError, match="at most one export credit"):
        version(fixture_export_credit(), fixture_export_credit(name="second_credit"))


def test_an_export_credit_needs_time_of_use_energy() -> None:
    with pytest.raises(ValidationError, match="needs a time-of-use energy charge"):
        fixture_version(
            fixture_flat("100"), fixture_export_credit(), tou_calendar=CALENDAR, billing=CAP
        )


def test_an_export_cap_without_a_credit_is_refused() -> None:
    with pytest.raises(ValidationError, match="no export credit"):
        fixture_version(fixture_tou_energy(), tou_calendar=CALENDAR, billing=CAP)


def test_a_negative_credit_rate_is_refused() -> None:
    with pytest.raises(ValidationError, match="must not be negative"):
        fixture_export_credit({**FIXTURE_EXPORT_CENTS, ("high", PEAK): "-1"})


def test_a_bill_of_exactly_zero_is_accepted() -> None:
    """Credit rate equal to the energy rate at peak: R500.00 - R500.00 = R0.00."""
    equal = fixture_export_credit({**FIXTURE_EXPORT_CENTS, ("high", PEAK): "500"})
    bill = calculate_bill(version(equal), JULY, profile(("100", "0", "0"), {PEAK: "100"}), VAT)
    assert bill.total.rand == 0
