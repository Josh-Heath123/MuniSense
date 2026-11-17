"""Property tests for money and rates (P1-2)."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from munisense.domain.money import Money, Rate, RateUnit, exact

# Rands and rates as printed: up to 10 integer digits, up to 6 decimals.
amounts = st.decimals(
    min_value=Decimal("-9999999999"),
    max_value=Decimal("9999999999"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)
non_negative = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("9999999999"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


@given(amounts, amounts, amounts)
def test_money_addition_is_associative_and_exact(a: Decimal, b: Decimal, c: Decimal) -> None:
    x, y, z = Money(rand=a), Money(rand=b), Money(rand=c)
    assert (x + y) + z == x + (y + z)
    assert ((x + y) + z).rand == a + b + c


@given(amounts, amounts)
def test_money_subtraction_inverts_addition(a: Decimal, b: Decimal) -> None:
    x, y = Money(rand=a), Money(rand=b)
    assert (x + y) - y == x


@given(non_negative)
def test_cents_to_rand_conversion_is_exact_and_reversible(cents: Decimal) -> None:
    rate = Rate(value=cents, unit=RateUnit.CENTS_PER_KWH)
    with exact():
        assert rate.canonical_value * 100 == cents


@given(non_negative)
def test_a_rand_rate_is_its_own_canonical_value(rand: Decimal) -> None:
    assert Rate(value=rand, unit=RateUnit.RAND_PER_KWH).canonical_value == rand
