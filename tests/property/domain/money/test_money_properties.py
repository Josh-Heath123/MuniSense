"""Property tests for money and rates (P1-2).

The strategies produce up to 40 significant digits, beyond the default decimal context's
28, so a result rounded by the default context would fail these tests. References are
computed in an independent, much wider context.
"""

from decimal import Decimal, localcontext

from hypothesis import given
from hypothesis import strategies as st

from munisense.domain.money import Money, Rate, RateUnit

WIDE_CONTEXT = 200


def _decimal(integer: int, places: int) -> Decimal:
    return Decimal(integer).scaleb(-places)


wide = st.builds(_decimal, st.integers(-(10**40), 10**40), st.integers(0, 15))
printed = st.builds(_decimal, st.integers(0, 10**15), st.integers(0, 12))


@given(wide, wide, wide)
def test_money_addition_is_associative_and_exact(a: Decimal, b: Decimal, c: Decimal) -> None:
    x, y, z = Money(rand=a), Money(rand=b), Money(rand=c)
    assert (x + y) + z == x + (y + z)
    with localcontext(prec=WIDE_CONTEXT):
        expected = a + b + c
    assert ((x + y) + z).rand == expected


@given(wide, wide)
def test_money_subtraction_inverts_addition(a: Decimal, b: Decimal) -> None:
    x, y = Money(rand=a), Money(rand=b)
    assert (x + y) - y == x


@given(printed)
def test_cents_to_rand_conversion_is_exact_and_reversible(cents: Decimal) -> None:
    rate = Rate(value=cents, unit=RateUnit.CENTS_PER_KWH)
    assert rate.canonical_value.scaleb(2) == cents
    assert rate.canonical_value.as_tuple().digits == cents.as_tuple().digits


@given(printed)
def test_a_rand_rate_is_its_own_canonical_value(rand: Decimal) -> None:
    for unit in (RateUnit.RAND_PER_KWH, RateUnit.RAND_PER_DAY, RateUnit.RAND_PER_MONTH):
        assert str(Rate(value=rand, unit=unit).canonical_value) == str(rand)


@given(printed, printed)
def test_a_charge_is_the_exact_product(cents_per_kwh: Decimal, kwh: Decimal) -> None:
    rate = Rate(value=cents_per_kwh, unit=RateUnit.CENTS_PER_KWH)
    with localcontext(prec=WIDE_CONTEXT):
        expected = cents_per_kwh * kwh / 100
    assert rate.charge(kwh).rand == expected
