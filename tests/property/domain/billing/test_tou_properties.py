"""Properties of time-of-use energy bills (P4-7). Rates and kWh are generated fixtures.

The P1 properties carried over: a bill is never negative; moving use to a dearer period
never lowers it (beyond rounding); VAT and the total add up; and splitting a month
changes the total by no more than rounding.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from munisense.domain.billing import (
    BillingPeriod,
    TimeOfUseBuckets,
    calculate_bill,
    calculate_period,
)
from munisense.domain.billing.splitting import _shares
from munisense.domain.money import RoundingPolicy, VatApplication
from munisense.domain.tariffs import TariffVersion, TouPeriod
from support.builders import (
    fixture_calendar,
    fixture_fixed,
    fixture_flat,
    fixture_policy,
    fixture_tou_energy,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
CALENDAR = fixture_calendar()
HALF_CENT = Decimal("0.005")
FACTOR_ALLOWANCE = Decimal("0.05")  # as P1: factors to 1e-6 on amounts below R20,000
PERIODS = (TouPeriod.PEAK, TouPeriod.STANDARD, TouPeriod.OFF_PEAK)

cents = st.integers(0, 50_000).map(lambda c: str(Decimal(c).scaleb(-2)))
# At most 1,000 kWh a period and R5.00 a kWh: under R30,000 a bill with the legacy charge,
# so rounding the factors to millionths moves a split total by under
# 30,000 x 1.125 x 0.0000005 x 2 parts, about R0.034, inside P1's R0.05 allowance.
kwh = st.integers(0, 1_000_000).map(lambda k: Decimal(k).scaleb(-3))
months = st.integers(0, 11).map(lambda m: date(2026 + (6 + m) // 12, (6 + m) % 12 + 1, 1))


def _version(
    rates: list[str],
    start: date = date(2026, 7, 1),
    end: date = date(2027, 7, 1),
    policy: RoundingPolicy | None = None,
    monthly: str | None = None,
) -> TariffVersion:
    energy = fixture_tou_energy(
        {
            (season, period): rates[i * 3 + j]
            for i, season in enumerate(("high", "low"))
            for j, period in enumerate(PERIODS)
        }
    )
    extra = (fixture_fixed(monthly),) if monthly is not None else ()
    return fixture_version(
        energy,
        fixture_flat(rates[6], name="legacy"),
        *extra,
        start=start,
        end=end,
        tou_calendar=CALENDAR,
        policy=policy,
    )


def _used(values: list[Decimal]) -> TimeOfUseBuckets:
    return TimeOfUseBuckets(used_kwh=dict(zip(PERIODS, values, strict=True)))


def _month(first: date) -> BillingPeriod:
    nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    return BillingPeriod(start=first, end=nxt)


applications = st.sampled_from(list(VatApplication))
CENT = Decimal("0.01")


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


@settings(max_examples=60)
@given(
    st.lists(cents, min_size=7, max_size=7),
    st.lists(kwh, min_size=3, max_size=3),
    months,
    applications,
)
def test_a_bill_is_never_negative_and_its_vat_and_total_add_up(
    rates: list[str], used: list[Decimal], first: date, application: VatApplication
) -> None:
    """VAT is the policy's: on each line, or once on the subtotal, at the fixture's 12.5%
    rounded to cents half up; the totals are the sums of the lines."""
    version = _version(rates, policy=fixture_policy(vat_application=application))
    bill = calculate_bill(version, _month(first), _used(used), VAT)
    assert bill.total.rand >= 0
    assert bill.subtotal.rand == sum((line.amount.rand for line in bill.lines), Decimal(0))
    if application is VatApplication.PER_LINE:
        for line in bill.lines:
            assert line.vat is not None
            assert line.vat.rand == _cents(line.amount.rand * Decimal("0.125"))
        assert bill.vat.rand == sum((line.vat.rand for line in bill.lines if line.vat), Decimal(0))
    else:
        assert bill.vat.rand == _cents(bill.subtotal.rand * Decimal("0.125"))
    assert bill.total.rand == bill.subtotal.rand + bill.vat.rand
    assert bill.consumption_kwh == sum(used, Decimal(0))


@settings(max_examples=60)
@given(
    st.lists(cents, min_size=7, max_size=7),
    st.lists(kwh, min_size=3, max_size=3),
    kwh,
    months,
    st.permutations(range(3)).map(lambda p: (p[0], p[1])),
)
def test_moving_use_to_a_period_no_cheaper_never_lowers_the_bill(
    rates: list[str], used: list[Decimal], moved: Decimal, first: date, pair: tuple[int, int]
) -> None:
    """Move kWh from one period to another whose rate (in the bill's season) is at least
    as high: the bill cannot fall, beyond the rounding of the two lines, VAT and the
    total."""
    source, target = pair
    season = 0 if 6 <= first.month <= 8 else 3
    if Decimal(rates[season + target]) < Decimal(rates[season + source]):
        rates[season + target] = rates[season + source]
    moved = min(moved, used[source])
    before = calculate_bill(_version(rates), _month(first), _used(used), VAT)
    after_used = list(used)
    after_used[source] -= moved
    after_used[target] += moved
    after = calculate_bill(_version(rates), _month(first), _used(after_used), VAT)
    roundings = 2 * 2 + 2  # two lines before and after, then VAT and the total
    assert after.total.rand >= before.total.rand - HALF_CENT * roundings * Decimal("1.125")


@settings(max_examples=40)
@given(
    st.lists(cents, min_size=7, max_size=7),
    st.lists(kwh, min_size=3, max_size=3),
    months,
    st.integers(1, 27),
    st.integers(0, 100_000).map(lambda c: str(Decimal(c).scaleb(-2))),
)
def test_splitting_a_month_changes_the_total_by_no_more_than_rounding(
    rates: list[str], used: list[Decimal], first: date, cut: int, monthly: str
) -> None:
    """P1's property: one month inside one season, split at a day between two versions
    with the same rates and a monthly basic charge (so month fractions are used), totals
    the unsplit bill within R0.005 per rounding plus P1's allowance for rounded factors."""
    month = _month(first)
    middle = first + timedelta(days=cut)
    whole = calculate_bill(_version(rates, monthly=monthly), month, _used(used), VAT)
    split = calculate_period(
        [
            _version(rates, end=middle, monthly=monthly),
            _version(rates, start=middle, end=date(2027, 7, 1), monthly=monthly),
        ],
        month,
        _used(used),
        VAT,
    )
    roundings = len(whole.lines) + sum(len(part.lines) for part in split.parts) + 2 * 3
    assert abs(split.total.rand - whole.total.rand) <= HALF_CENT * roundings + FACTOR_ALLOWANCE


@settings(max_examples=60)
@given(st.lists(kwh, min_size=3, max_size=3), st.integers(1, 89))
def test_each_periods_shares_add_up_to_the_share_of_the_total(
    used: list[Decimal], days: int
) -> None:
    """Sharing each period's kWh on its own, with the same factors, gives each part the
    same total as sharing the period total (P4-7 review)."""
    version = _version(["100"] * 7, start=date(2026, 4, 1))
    start = date(2026, 6, 1)
    period = BillingPeriod(start=start, end=start + timedelta(days=days + 1))
    bill = calculate_period([version], period, _used(used), VAT)
    ranges = [part.period for part in bill.parts]
    expected = _shares(sum(used, Decimal(0)), period, ranges, version)
    assert [part.consumption_kwh for part in bill.parts] == expected
