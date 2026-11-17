"""Property tests for the forward engine (P1-7, testing strategy).

- A bill is never negative.
- A block bill never falls as consumption rises.
- VAT equals the rate times the VAT-able subtotal, within the policy's rounding.
- Extreme inputs end in a bill or a domain error, never an unhandled exception.
"""

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from munisense.domain.base import DomainError
from munisense.domain.billing import BillingPeriod, PeriodTotal, calculate_bill
from munisense.domain.money import VatApplication
from support.builders import (
    fixture_blocks,
    fixture_fixed,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
VAT = fixture_vat_table()
HALF_CENT = Decimal("0.005")


def _decimal(integer: int, places: int) -> Decimal:
    return Decimal(integer).scaleb(-places)


kwh = st.builds(_decimal, st.integers(0, 10**7), st.integers(0, 3))
cents = st.builds(_decimal, st.integers(0, 10**6), st.integers(0, 4))
thresholds = st.lists(st.integers(1, 2000), min_size=0, max_size=4, unique=True).map(sorted)
policies = st.sampled_from(
    [
        fixture_policy(),
        fixture_policy(vat_application=VatApplication.PER_LINE),
        fixture_policy(line_amount=None),
    ]
)


@st.composite
def block_tariffs(draw: st.DrawFn) -> object:
    bounds = draw(thresholds)
    rates = draw(st.lists(cents, min_size=len(bounds) + 1, max_size=len(bounds) + 1))
    pairs = [(str(b), str(r)) for b, r in zip(bounds, rates, strict=False)]
    pairs.append((None, str(rates[-1])))  # type: ignore[arg-type]  # None marks the open block
    fixed = draw(cents)
    return fixture_version(fixture_fixed(str(fixed)), fixture_blocks(*pairs), policy=draw(policies))


@given(block_tariffs(), kwh)
def test_a_bill_is_never_negative(tariff: object, used: Decimal) -> None:
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=used), VAT)  # type: ignore[arg-type]
    assert bill.total.rand >= 0
    assert all(line.amount.rand >= 0 for line in bill.lines)


@given(block_tariffs(), kwh, kwh)
def test_a_block_bill_never_falls_as_consumption_rises(
    tariff: object, a: Decimal, b: Decimal
) -> None:
    low, high = sorted((a, b))
    bill_low = calculate_bill(tariff, JULY, PeriodTotal(kwh=low), VAT)  # type: ignore[arg-type]
    bill_high = calculate_bill(tariff, JULY, PeriodTotal(kwh=high), VAT)  # type: ignore[arg-type]
    assert bill_low.subtotal.rand <= bill_high.subtotal.rand
    assert bill_low.total.rand <= bill_high.total.rand


@given(block_tariffs(), kwh)
def test_vat_equals_the_rate_times_the_vatable_subtotal_within_rounding(
    tariff: object, used: Decimal
) -> None:
    bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=used), VAT)  # type: ignore[arg-type]
    exact_vat = bill.subtotal.rand * bill.vat_rate.fraction  # every fixture line is standard
    allowed = HALF_CENT * max(1, len(bill.lines))  # one half-cent per rounding at most
    assert abs(bill.vat.rand - exact_vat) <= allowed


@given(
    st.builds(_decimal, st.integers(0, 10**15 - 1), st.integers(0, 12)),
    st.builds(_decimal, st.integers(0, 10**15 - 1), st.integers(0, 12)),
)
def test_extreme_values_end_in_a_bill_or_a_domain_error(used: Decimal, rate: Decimal) -> None:
    tariff = fixture_version(fixture_fixed("1"), fixture_blocks(("50", "1"), (None, str(rate))))
    try:
        bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=used), VAT)
    except DomainError:
        return
    assert bill.total.rand >= 0
