"""Property tests for the forward engine (P1-7, testing strategy).

References are computed independently from the tariff's inputs, not from the bill:

Tariffs are drawn with a fixed charge, block energy and, since P1-11, sometimes a per-kWh
levy and a free basic allocation (applied when the customer is drawn as eligible).

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
from munisense.domain.billing import Bill, BillingPeriod, PeriodTotal, calculate_bill
from munisense.domain.money import Quantisation, RoundingMode, RoundingPolicy, VatApplication
from munisense.domain.tariffs import Component, TariffVersion, VatTreatment
from support.builders import (
    fixture_blocks,
    fixture_fixed,
    fixture_free_basic,
    fixture_levy,
    fixture_policy,
    fixture_vat_table,
    fixture_version,
)

JULY = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
VAT = fixture_vat_table()
FRACTION = Decimal("0.125")
CENT = Decimal("0.01")
WIDE = 200


def _decimal(integer: int, places: int) -> Decimal:
    return Decimal(integer).scaleb(-places)


cents = st.builds(_decimal, st.integers(0, 10**6), st.integers(0, 4))
treatments = st.sampled_from(list(VatTreatment))
# Cents in every mode that matters for credits: half-up, half-even and the two that are
# not symmetric about zero (floor, ceiling); the same mode at every point of a policy.
POINTS = [
    Quantisation(step=Decimal("0.01"), mode=mode)
    for mode in (
        RoundingMode.HALF_UP,
        RoundingMode.HALF_EVEN,
        RoundingMode.FLOOR,
        RoundingMode.CEILING,
    )
]
policies = st.builds(
    lambda point, per_line, line_rounded: fixture_policy(
        line_amount=point if line_rounded else None,
        vat_application=VatApplication.PER_LINE if per_line else VatApplication.ON_SUBTOTAL,
        vat_amount=point,
        total=point,
    ),
    st.sampled_from(POINTS),
    st.booleans(),
    st.booleans(),
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
    levy_cents: Decimal | None = None
    levy_vat: VatTreatment = VatTreatment.STANDARD
    free_kwh: Decimal | None = None
    eligible: bool = False

    def bill(self, kwh: Decimal | None = None) -> Bill:
        used = self.kwh if kwh is None else kwh
        return calculate_bill(
            self.tariff, JULY, PeriodTotal(kwh=used), VAT, free_basic_eligible=self.eligible
        )


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
    levy_cents = draw(st.none() | cents)
    levy_vat = draw(treatments)
    free_kwh = draw(st.none() | st.builds(_decimal, st.integers(1, 3_000_000), st.integers(0, 3)))
    eligible = free_kwh is not None and draw(st.booleans())
    components: list[Component] = [
        fixture_fixed(str(fixed)),
        fixture_blocks(*pairs, vat=energy_vat),
    ]
    if levy_cents is not None:
        components.append(fixture_levy(str(levy_cents), vat=levy_vat))
    if free_kwh is not None:
        components.append(fixture_free_basic(str(free_kwh), vat=energy_vat))
    tariff = fixture_version(*components, policy=policy)
    edges = [Decimal(b) for b in bounds] + ([free_kwh] if free_kwh is not None else [])
    near = [e + Decimal(offset).scaleb(-3) for e in edges for offset in (-1, 0, 1) if e > 0]
    kwh = draw(
        st.one_of(
            st.builds(_decimal, st.integers(0, 10**7), st.integers(0, 3)),
            st.sampled_from(near) if near else st.just(Decimal(0)),
        )
    )
    return Case(
        tariff,
        fixed,
        bounds,
        rates,
        energy_vat,
        policy,
        kwh,
        levy_cents,
        levy_vat,
        free_kwh,
        eligible,
    )


def _edge_case(free: str, kwh: str, mode: RoundingMode) -> Case:
    """An explicit case: blocks up to 50 and 350 kWh, 152.37c / 201.11c / 257.89c, a R100.00
    fixed charge, standard VAT, an eligible allocation, the same mode at every point."""
    point = Quantisation(step=Decimal("0.01"), mode=mode)
    policy = fixture_policy(line_amount=point, vat_amount=point, total=point)
    rates = [Decimal("152.37"), Decimal("201.11"), Decimal("257.89")]
    tariff = fixture_version(
        fixture_fixed("100.00"),
        fixture_blocks(("50", "152.37"), ("350", "201.11"), (None, "257.89")),
        fixture_free_basic(free),
        policy=policy,
    )
    return Case(
        tariff,
        Decimal("100.00"),
        [50, 350],
        rates,
        VatTreatment.STANDARD,
        policy,
        Decimal(kwh),
        None,
        VatTreatment.STANDARD,
        Decimal(free),
        eligible=True,
    )


EDGE_CASES = [
    _edge_case("60", "60", RoundingMode.FLOOR),  # use exactly equal to the allocation
    _edge_case("50", "412.3", RoundingMode.FLOOR),  # allocation ends on a threshold
    _edge_case("60", "30.5", RoundingMode.CEILING),  # credit with a non-zero last digit
]


def _expected_quantities(case: Case, kwh: Decimal | None = None) -> list[Decimal]:
    used = case.kwh if kwh is None else kwh
    lowers = [Decimal(0), *(Decimal(b) for b in case.bounds)]
    uppers: list[Decimal | None] = [*(Decimal(b) for b in case.bounds), None]
    return [
        max(Decimal(0), (used if up is None else min(used, up)) - low)
        for low, up in zip(lowers, uppers, strict=True)
    ]


def _quantised(value: Decimal, point: Quantisation | None) -> Decimal:
    # A credit is rounded as its magnitude, then negated (`Money.quantised`).
    if point is None:
        return value
    return -point.apply(-value) if value < 0 else point.apply(value)


@given(cases())
def test_block_quantities_add_up_and_stay_inside_their_blocks(case: Case) -> None:
    bill = case.bill()
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
@example(EDGE_CASES[0])
@example(EDGE_CASES[1])
@example(EDGE_CASES[2])
def test_amounts_and_vat_match_an_independent_calculation(case: Case) -> None:
    bill = case.bill()
    point = case.policy.line_amount
    with localcontext(prec=WIDE):
        energy = [
            _quantised(q * r / 100, point)
            for q, r in zip(_expected_quantities(case), case.rates, strict=True)
            if q > 0
        ]
        fixed = _quantised(case.fixed_rand, point)
        levy = (
            [_quantised(case.kwh * case.levy_cents / 100, point)]
            if case.levy_cents is not None and case.kwh > 0
            else []
        )
        credits = []
        if case.eligible and case.free_kwh is not None:
            free = min(case.kwh, case.free_kwh)
            credits = [
                _quantised(-(q * r / 100), point)
                for q, r in zip(_expected_quantities(case, free), case.rates, strict=True)
                if q > 0
            ]
        subtotal = (
            fixed + sum(energy, Decimal(0)) + sum(levy, Decimal(0)) + sum(credits, Decimal(0))
        )
        standard = [
            fixed,
            *(energy if case.energy_vat is VatTreatment.STANDARD else []),
            *(levy if case.levy_vat is VatTreatment.STANDARD else []),
            *(credits if case.energy_vat is VatTreatment.STANDARD else []),
        ]
        exact_vat = sum(standard, Decimal(0)) * FRACTION
    assert bill.subtotal.rand == subtotal
    if case.policy.vat_application is VatApplication.ON_SUBTOTAL:
        assert bill.vat.rand == _quantised(exact_vat, case.policy.vat_amount)
    else:
        # Each standard line's VAT is rounded once: within half a cent per line for the half
        # modes, one cent for floor and ceiling.
        point = case.policy.vat_amount
        half = point is not None and point.mode in {RoundingMode.HALF_UP, RoundingMode.HALF_EVEN}
        per_line = CENT / 2 if half else CENT
        assert abs(bill.vat.rand - exact_vat) <= per_line * len(standard)
    assert bill.total.rand == _quantised(bill.subtotal.rand + bill.vat.rand, case.policy.total)


@given(cases())
@example(EDGE_CASES[0])
@example(EDGE_CASES[1])
@example(EDGE_CASES[2])
def test_a_bill_is_never_negative(case: Case) -> None:
    bill = case.bill()
    assert bill.total.rand >= 0
    assert bill.subtotal.rand >= 0
    assert all(line.amount.rand >= 0 for line in bill.lines if line.component != "free_basic")


@given(cases(), st.builds(_decimal, st.integers(0, 10**7), st.integers(0, 3)))
def test_a_block_bill_never_falls_as_consumption_rises(case: Case, other: Decimal) -> None:
    low, high = sorted((case.kwh, other))
    bill_low, bill_high = case.bill(low), case.bill(high)
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
