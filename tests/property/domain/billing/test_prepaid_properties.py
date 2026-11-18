"""Property tests for prepaid purchases (P1-14).

Random tariffs with two block components whose thresholds differ (energy and a "network"
charge, each up to three thresholds and rates up to R5 a kWh), random kWh already bought in
the month (whole hundredths, as receipts give them), random amounts; fixture VAT 12.5%; kWh
rounded once per purchase to hundredths in every mode. The forward cost is computed
independently: the kWh received are walked through both components' blocks from the
month's kWh so far, each kWh at the sum of its two rates, with VAT.

- More money never buys fewer kWh.
- The forward cost of the kWh received does not exceed the money paid, beyond the stated
  rounding (none for down and floor; half a hundredth of a kWh at the last price for the
  half modes; a whole hundredth for up and ceiling), and leaves at most a hundredth of a
  kWh's worth unspent.
- A month of purchases costs what the forward engine bills for the month's kWh: the
  payments and the bill agree within the roundings of both (one kWh rounding per purchase
  at the dearest price, and the bill's line, VAT and total roundings).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from hypothesis import example, given
from hypothesis import strategies as st

from munisense.domain.billing import (
    BillingPeriod,
    MonthSoFar,
    PeriodTotal,
    calculate_bill,
    calculate_month,
    calculate_purchase,
)
from munisense.domain.money import Money, Quantisation, RoundingMode
from munisense.domain.tariffs import PrepaidFixedCharges, TariffVersion
from support.builders import (
    fixture_billing_policy,
    fixture_blocks,
    fixture_fixed,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

VAT = fixture_vat_table()
WITH_VAT = Decimal("1.125")
STEP = Decimal("0.01")
DAY = date(2026, 7, 15)
WIDE = 200
ALLOWANCE = {  # how far above the money the rounded kWh may cost, in steps at the last price
    RoundingMode.DOWN: Decimal(0),
    RoundingMode.FLOOR: Decimal(0),
    RoundingMode.HALF_UP: Decimal("0.5"),
    RoundingMode.HALF_EVEN: Decimal("0.5"),
    RoundingMode.UP: Decimal(1),
    RoundingMode.CEILING: Decimal(1),
}

bounds = st.lists(st.integers(1, 1000), max_size=3, unique=True).map(sorted)
cents = st.integers(1, 50_000).map(lambda c: Decimal(c).scaleb(-2))  # 0.01c to 500c
rates = st.lists(cents, min_size=4, max_size=4)
money = st.integers(0, 500_000).map(lambda c: Decimal(c).scaleb(-2))
kwh_so_far = st.integers(0, 200_000).map(lambda k: Decimal(k).scaleb(-2))
modes = st.sampled_from(list(ALLOWANCE))

type Blocks = tuple[list[int], list[Decimal]]


def _pairs(blocks: Blocks) -> list[tuple[str | None, str]]:
    edges, prices = blocks
    pairs: list[tuple[str | None, str]] = [
        (str(edge), str(price)) for edge, price in zip(edges, prices, strict=False)
    ]
    pairs.append((None, str(prices[len(edges)])))
    return pairs


def _tariff(energy: Blocks, network: Blocks, mode: RoundingMode) -> TariffVersion:
    return fixture_version(
        fixture_blocks(*_pairs(energy)),
        fixture_blocks(*_pairs(network), name="network"),
        policy=fixture_policy(prepaid_kwh=Quantisation(step=STEP, mode=mode)),
        billing=fixture_billing_policy(fixed_charges=PrepaidFixedCharges.NOT_FROM_PURCHASES),
    )


def _rate_at(blocks: Blocks, kwh: Decimal) -> Decimal:
    edges, prices = blocks
    for edge, price in zip(edges, prices, strict=False):
        if kwh < edge:
            return price / 100
    return prices[len(edges)] / 100


def _price_at(energy: Blocks, network: Blocks, kwh: Decimal) -> Decimal:
    return (_rate_at(energy, kwh) + _rate_at(network, kwh)) * WITH_VAT


def _cost(energy: Blocks, network: Blocks, before: Decimal, kwh: Decimal) -> Decimal:
    """Independent forward cost, with VAT, of `kwh` bought after `before` kWh: the sum over
    both components of the kWh in each of their blocks at that block's rate."""
    total = Decimal(0)
    with localcontext(prec=WIDE):
        for edges, prices in (energy, network):
            lower = Decimal(0)
            for upper, price in zip([*edges, None], prices, strict=False):
                top = before + kwh if upper is None else min(Decimal(upper), before + kwh)
                total += max(Decimal(0), top - max(lower, before)) * price / 100 * WITH_VAT
                if upper is not None:
                    lower = Decimal(upper)
    return total


@given(bounds, rates, bounds, rates, kwh_so_far, money, money, modes)
def test_more_money_never_buys_fewer_kwh(
    energy_edges: list[int],
    energy_rates: list[Decimal],
    network_edges: list[int],
    network_rates: list[Decimal],
    before: Decimal,
    one: Decimal,
    other: Decimal,
    mode: RoundingMode,
) -> None:
    low, high = sorted((one, other))
    version = _tariff((energy_edges, energy_rates), (network_edges, network_rates), mode)
    so_far = MonthSoFar(purchases=1, kwh=before)
    less = calculate_purchase(version, DAY, Money(rand=low), so_far, VAT)
    more = calculate_purchase(version, DAY, Money(rand=high), so_far, VAT)
    assert less.kwh <= more.kwh


NO_NETWORK = [Decimal(0)] * 4


@given(bounds, rates, bounds, rates, kwh_so_far, money, modes)
# The reviewer's counterexamples (B1), moved onto the hundredths grid (off-grid kWh so far
# is refused; see the unit tests): a cheap block then a dear one, rounded down; and a dear
# block then a cheap one, rounded half up.
@example(
    [1],
    [Decimal(1), Decimal(500)] * 2,
    [],
    NO_NETWORK,
    Decimal("0.01"),
    Decimal("0.02"),
    RoundingMode.DOWN,
)
@example(
    [1],
    [Decimal(500), Decimal("0.01")] * 2,
    [],
    NO_NETWORK,
    Decimal("0.01"),
    Decimal("5.60"),
    RoundingMode.HALF_UP,
)
def test_the_kwh_received_cost_what_was_paid_within_the_rounding(
    energy_edges: list[int],
    energy_rates: list[Decimal],
    network_edges: list[int],
    network_rates: list[Decimal],
    before: Decimal,
    paid: Decimal,
    mode: RoundingMode,
) -> None:
    energy, network = (energy_edges, energy_rates), (network_edges, network_rates)
    version = _tariff(energy, network, mode)
    purchase = calculate_purchase(
        version, DAY, Money(rand=paid), MonthSoFar(purchases=1, kwh=before), VAT
    )
    cost = _cost(energy, network, before, purchase.kwh)
    # The rounding falls inside the last segment: its price is the price just below the
    # kWh reached, or at it when a purchase ends exactly on a threshold.
    reached = before + purchase.kwh
    last_price = max(
        _price_at(energy, network, reached - STEP / 2), _price_at(energy, network, reached)
    )
    assert cost <= paid + ALLOWANCE[mode] * STEP * last_price
    assert paid - cost <= STEP * last_price
    assert all(segment.kwh >= 0 for segment in purchase.segments)


@given(
    bounds,
    rates,
    st.integers(0, 50_000).map(lambda c: Decimal(c).scaleb(-2)),
    st.lists(st.integers(0, 100_000).map(lambda c: Decimal(c).scaleb(-2)), min_size=1, max_size=4),
)
def test_a_month_of_purchases_costs_what_the_month_is_billed(
    edges: list[int], prices: list[Decimal], fixed: Decimal, payments: list[Decimal]
) -> None:
    # One block component, a monthly fixed charge taken from the first purchase, half up.
    version = fixture_version(
        fixture_fixed(str(fixed)),
        fixture_blocks(*_pairs((edges, prices))),
        policy=fixture_policy(prepaid_kwh=Quantisation(step=STEP, mode=RoundingMode.HALF_UP)),
        billing=fixture_billing_policy(),
    )
    vat = (fixed * Decimal("0.125")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    first = max(payments[0], fixed + vat)  # the first purchase covers the fixed charges
    paid = [first, *payments[1:]]
    days = [date(2026, 7, 1 + index) for index in range(len(paid))]
    purchases = calculate_month(
        version, [(d, Money(rand=p)) for d, p in zip(days, paid, strict=True)], VAT
    )
    bill = calculate_bill(
        version,
        BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1)),
        PeriodTotal(kwh=purchases[-1].month_kwh_after),
        VAT,
    )
    dearest = max(prices) / 100 * WITH_VAT
    kwh_roundings = len(purchases) * (STEP / 2) * dearest
    bill_roundings = Decimal("0.005") * (len(bill.lines) + 2) * WITH_VAT + Decimal("0.01")
    assert abs(sum(paid, Decimal(0)) - bill.total.rand) <= kwh_roundings + bill_roundings
