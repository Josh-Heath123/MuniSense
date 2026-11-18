"""Property tests for the forward engine (P1-7, testing strategy).

References are computed independently from the tariff's inputs, not from the bill:

- Block quantities add up to the consumption, and each closed block holds at most its width.
- Without line rounding, the subtotal equals the sum of rate x quantity, exactly.
- VAT equals the rate times the independently computed VAT-able base, within one rounding
  (VAT on the subtotal) or one rounding per standard-rated line (VAT per line).
- A bill is never negative and never falls as consumption rises.
- Extreme inputs end in a bill or a domain error, never another exception.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from itertools import pairwise

from hypothesis import example, given
from hypothesis import strategies as st

from munisense.domain.base import DomainError
from munisense.domain.billing import BillingPeriod, PeriodTotal, calculate_bill
from munisense.domain.money import Quantisation, RoundingPolicy, VatApplication
from munisense.domain.tariffs import TariffVersion, VatTreatment
from support.builders import (
    CENTS_HALF_UP,
    fixture_blocks,
    fixture_fixed,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
VAT = fixture_vat_table()
FRACTION = Decimal("0.125")
HALF_CENT = Decimal("0.005")
WIDE = 200


def _decimal(integer: int, places: int) -> Decimal:
    return Decimal(integer).scaleb(-places)


cents = st.builds(_decimal, st.integers(0, 10**6), st.integers(0, 4))
treatments = st.sampled_from(list(VatTreatment))
policies = st.sampled_from(
    [
        fixture_policy(),
        fixture_policy(vat_application=VatApplication.PER_LINE),
        fixture_policy(line_amount=None),
        fixture_policy(line_amount=None, vat_application=VatApplication.PER_LINE),
    ]
)


@dataclass(frozen=True)
class Case:
    tariff: TariffVersion
    fixed_rand: Decimal
    bounds: list[int]
    rates: list[Decimal]  # cents per kWh, one per block
    energy_vat: VatTreatment
    policy: RoundingPolicy
    kwh: Decimal


@st.composite
def cases(draw: st.DrawFn) -> Case:
    bounds = sorted(draw(st.lists(st.integers(1, 2000), max_size=4, unique=True)))
    rates = draw(st.lists(cents, min_size=len(bounds) + 1, max_size=len(bounds) + 1))
    pairs: list[tuple[str | None, str]] = [
        (str(b), str(r)) for b, r in zip(bounds, rates, strict=False)
    ]
    pairs.append((None, str(rates[-1])))
    fixed = draw(cents)
    energy_vat = draw(treatments)
    policy = draw(policies)
    tariff = fixture_version(
        fixture_fixed(str(fixed)), fixture_blocks(*pairs, vat=energy_vat), policy=policy
    )
    near = [_decimal(b * 1000 + offset, 3) for b in bounds for offset in (-1, 0, 1)]
    kwh = draw(
        st.one_of(
            st.builds(_decimal, st.integers(0, 10**7), st.integers(0, 3)),
            st.sampled_from(near) if near else st.just(Decimal(0)),
        )
    )
    return Case(tariff, fixed, bounds, rates, energy_vat, policy, kwh)


def _expected_quantities(case: Case) -> list[Decimal]:
    lowers = [Decimal(0), *(Decimal(b) for b in case.bounds)]
    uppers: list[Decimal | None] = [*(Decimal(b) for b in case.bounds), None]
    return [
        max(Decimal(0), (case.kwh if up is None else min(case.kwh, up)) - low)
        for low, up in zip(lowers, uppers, strict=True)
    ]


def _quantised(value: Decimal, point: Quantisation | None) -> Decimal:
    return value if point is None else point.apply(value)


@given(cases())
def test_block_quantities_add_up_and_stay_inside_their_blocks(case: Case) -> None:
    bill = calculate_bill(case.tariff, JULY, PeriodTotal(kwh=case.kwh), VAT)
    energy = [line for line in bill.lines if line.component == "energy"]
    expected = [q for q in _expected_quantities(case) if q > 0]
    assert [line.quantity for line in energy] == expected
    assert sum((line.quantity for line in energy), Decimal(0)) == case.kwh
    widths = [Decimal(b) - Decimal(a) for a, b in pairwise([0, *case.bounds])]
    for line in energy:  # each line used from a closed block holds at most that block's width
        number = int(line.description.split(":")[0].removeprefix("block "))
        if number <= len(widths):
            assert 0 < line.quantity <= widths[number - 1]


@given(cases())
def test_amounts_and_vat_match_an_independent_calculation(case: Case) -> None:
    bill = calculate_bill(case.tariff, JULY, PeriodTotal(kwh=case.kwh), VAT)
    point = case.policy.line_amount
    with localcontext(prec=WIDE):
        energy = [
            _quantised(q * r / 100, point)
            for q, r in zip(_expected_quantities(case), case.rates, strict=True)
            if q > 0
        ]
        fixed = _quantised(case.fixed_rand, point)
        subtotal = fixed + sum(energy, Decimal(0))
        standard = [fixed, *(energy if case.energy_vat is VatTreatment.STANDARD else [])]
        exact_vat = sum(standard, Decimal(0)) * FRACTION
    assert bill.subtotal.rand == subtotal
    if case.policy.vat_application is VatApplication.ON_SUBTOTAL:
        assert bill.vat.rand == CENTS_HALF_UP.apply(exact_vat)
    else:
        assert abs(bill.vat.rand - exact_vat) <= HALF_CENT * len(standard)
    assert bill.total.rand == CENTS_HALF_UP.apply(bill.subtotal.rand + bill.vat.rand)


@given(cases())
def test_a_bill_is_never_negative(case: Case) -> None:
    bill = calculate_bill(case.tariff, JULY, PeriodTotal(kwh=case.kwh), VAT)
    assert bill.total.rand >= 0
    assert all(line.amount.rand >= 0 for line in bill.lines)


@given(cases(), st.builds(_decimal, st.integers(0, 10**7), st.integers(0, 3)))
def test_a_block_bill_never_falls_as_consumption_rises(case: Case, other: Decimal) -> None:
    low, high = sorted((case.kwh, other))
    bill_low = calculate_bill(case.tariff, JULY, PeriodTotal(kwh=low), VAT)
    bill_high = calculate_bill(case.tariff, JULY, PeriodTotal(kwh=high), VAT)
    assert bill_low.subtotal.rand <= bill_high.subtotal.rand
    assert bill_low.total.rand <= bill_high.total.rand


exponent_edge = st.builds(
    lambda digits, exponent: Decimal(f"{digits}E{exponent}"),
    st.integers(1, 10**20),
    st.integers(-60, 40),
)


@given(exponent_edge, exponent_edge, exponent_edge, policies)
# The low edge of the rate's exponent, where cents become rand below the exact range.
@example(Decimal(100), Decimal("1E-60"), Decimal(1), fixture_policy())
@example(Decimal(100), Decimal("1E-59"), Decimal(1), fixture_policy())
@example(Decimal(100), Decimal("1E-58"), Decimal(1), fixture_policy(line_amount=None))
def test_extreme_values_end_in_a_bill_or_a_domain_error(
    used: Decimal, rate: Decimal, fixed: Decimal, policy: RoundingPolicy
) -> None:
    # Python-mode values up to the edge of ExactDecimal (60 digits, exponent +-60); any
    # exception other than a DomainError fails the test.
    try:
        tariff = fixture_version(
            fixture_fixed(str(fixed)),
            fixture_blocks(("50", "1"), (None, str(rate))),
            policy=policy,
        )
    except ValueError:
        return  # the values themselves are out of range: refused at construction
    try:
        bill = calculate_bill(tariff, JULY, PeriodTotal(kwh=used), VAT)
    except DomainError:
        return
    assert bill.total.rand >= 0
