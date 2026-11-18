"""Property tests for period splitting (P1-13, ADR-0011).

- Splitting a calendar month at any day into two identical versions changes the total by
  no more than the rounding allows: half a cent per rounded line, VAT and total (the
  fixture rounds all three to cents, half up), plus the effect of rounding the factors to
  millionths. That effect is at most half a millionth of each pro-rated amount per part:
  the drawn fixed charge is under R1,000 and the energy under 2,000 kWh x R5.00 = R10,000,
  so with VAT at 12.5% it is under (1,000 + 10,000) x 1.125 x 0.0000005 x 2 parts, about
  R0.012, and R0.05 allows for that with room to spare.
- For any period, the parts' kWh are never negative and add up to the period's kWh
  exactly, and the parts tile the period without gaps or overlaps.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from munisense.domain.billing import BillingPeriod, PeriodTotal, calculate_bill, calculate_period
from munisense.domain.money import RateUnit
from support.builders import (
    fixture_blocks,
    fixture_fixed,
    fixture_flat,
    fixture_season,
    fixture_seasonal,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
HALF_CENT = Decimal("0.005")
FACTOR_ALLOWANCE = Decimal("0.05")  # factors to 1e-6 on amounts below R20,000
START, END = date(2026, 7, 1), date(2027, 7, 1)

months = st.integers(0, 11).map(lambda m: date(2026 + (6 + m) // 12, (6 + m) % 12 + 1, 1))
cents = st.integers(0, 50_000).map(lambda c: str(Decimal(c).scaleb(-2)))


@given(
    months,
    st.integers(1, 27),
    st.lists(st.integers(1, 1000), max_size=3, unique=True).map(sorted),
    st.lists(cents, min_size=4, max_size=4),
    st.integers(0, 100_000).map(lambda c: str(Decimal(c).scaleb(-2))),
    st.integers(0, 2_000_000).map(lambda k: Decimal(k).scaleb(-3)),
)
def test_splitting_a_month_changes_the_total_by_no_more_than_rounding(
    first: date, cut: int, bounds: list[int], rates: list[str], fixed: str, used: Decimal
) -> None:
    pairs: list[tuple[str | None, str]] = [(str(b), r) for b, r in zip(bounds, rates, strict=False)]
    pairs.append((None, rates[len(bounds)]))
    components = (fixture_fixed(fixed), fixture_blocks(*pairs))
    month_days = calendar.monthrange(first.year, first.month)[1]
    month = BillingPeriod(start=first, end=first + timedelta(days=month_days))
    middle = first + timedelta(days=cut)
    whole = calculate_bill(fixture_version(*components), month, PeriodTotal(kwh=used), VAT)
    split = calculate_period(
        [
            fixture_version(*components, start=START, end=middle),
            fixture_version(*components, start=middle, end=END),
        ],
        month,
        PeriodTotal(kwh=used),
        VAT,
    )
    roundings = len(whole.lines) + sum(len(part.lines) for part in split.parts) + 2 * 3
    assert abs(split.total.rand - whole.total.rand) <= HALF_CENT * roundings + FACTOR_ALLOWANCE


@given(
    st.integers(0, 364).map(lambda d: START + timedelta(days=d)),
    st.integers(1, 365),
    st.integers(0, 10_000_000).map(lambda k: Decimal(k).scaleb(-3)),
)
def test_parts_tile_the_period_and_share_the_kwh_exactly(
    start: date, length: int, used: Decimal
) -> None:
    period = BillingPeriod(start=start, end=start + timedelta(days=length))
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), (None, "300.00")),
        fixture_season("low", (9, 1), (5, 31), (None, "200.00")),
    )
    tariff = fixture_version(
        fixture_fixed("1.00", RateUnit.RAND_PER_DAY),
        fixture_fixed("10.00", name="monthly"),
        seasonal,
        end=None,
    )
    bill = calculate_period([tariff], period, PeriodTotal(kwh=used), VAT)
    shares = [part.consumption_kwh for part in bill.parts]
    assert all(share >= 0 for share in shares)
    assert sum(shares, Decimal(0)) == used
    assert bill.parts[0].period.start == period.start
    assert bill.parts[-1].period.end == period.end
    for earlier, later in zip(bill.parts, bill.parts[1:], strict=False):
        assert earlier.period.end == later.period.start
    assert bill.total.rand == sum((part.total.rand for part in bill.parts), Decimal(0))


@given(st.integers(0, 2_000_000).map(lambda k: Decimal(k).scaleb(-3)))
def test_a_flat_rate_period_costs_what_its_days_and_kwh_cost(used: Decimal) -> None:
    # No monthly values: whatever the split, the energy is the kWh at the flat rate, to
    # within a half cent per line.
    period = BillingPeriod(start=date(2026, 7, 10), end=date(2026, 9, 20))
    tariff = fixture_version(fixture_flat("100.00"), end=None)
    bill = calculate_period([tariff], period, PeriodTotal(kwh=used), VAT)
    lines = [line for part in bill.parts for line in part.lines]
    assert abs(sum((line.amount.rand for line in lines), Decimal(0)) - used) <= HALF_CENT * len(
        lines
    )
