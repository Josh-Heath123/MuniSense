"""Prepaid purchases (P1-14, ADR-0004 "prepaid purchase" direction): the kWh a rand amount
buys, given the kWh already bought in the same calendar month, using the same components
and policies as a bill.

1. Refuse what cannot be calculated: a day outside the version, prices including VAT, a
   free basic allocation for an eligible customer (prepaid free tokens are not built), and
   a missing eligibility input where the tariff has an allocation.
2. Fixed charges (billing policy `prepaid_fixed_charges`): either the month's fixed
   charges and levies, with VAT, are deducted from the month's first purchase, priced by
   the forward engine as a bill for that month at zero kWh; or nothing is deducted.
3. The rest buys energy. The kWh of the month (block reset: calendar month) are cut into
   segments at every block threshold of every component; in each segment one kWh costs
   the sum of every per-kWh rate (energy, the season's rates, per-kWh levies), each with
   VAT if it is standard-rated. Walking from the kWh already bought, each segment is filled
   in turn; the money left in the last segment buys money / price kWh, exactly.
4. The kWh are rounded once, at the rounding policy's `prepaid_kwh` point. The month's
   kWh so far and every threshold must be whole multiples of that step (receipts give kWh
   to the step; anything finer is refused), so the whole segments are whole steps and the
   rounding falls inside the last segment, at its price, without crossing a threshold.

The forward cost of the kWh received equals the energy money, up to that one rounding: at
most half a step at the last segment's price for the half modes, a whole step for up and
ceiling, and never more than the money for down and floor.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import assert_never

from munisense.domain.billing.engine import check_price_basis, price_part
from munisense.domain.billing.errors import (
    FreeBasicEligibilityRequiredError,
    InvalidPurchaseError,
    PeriodOutsideVersionError,
    PrepaidNotSupportedError,
    PrepaidPrecisionError,
    PurchasesNotInOneMonthError,
    PurchaseTooSmallError,
)
from munisense.domain.billing.result import (
    BillWarning,
    LineItem,
    MonthSoFar,
    Purchase,
    PurchaseSegment,
    Source,
    SourceRole,
    WarningCode,
)
from munisense.domain.citations import Cited, StatusKind, cited_statuses, weakest_kind
from munisense.domain.money import (
    CanonicalUnit,
    Money,
    Quantisation,
    Rate,
    VatRate,
    VatTable,
    exact,
)
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import (
    Block,
    BlockEnergy,
    BlockReset,
    Component,
    FixedCharge,
    FlatEnergy,
    Levy,
    PrepaidFixedCharges,
    SeasonalEnergy,
    TariffVersion,
    VatTreatment,
)


def calculate_purchase(  # the inputs of one purchase
    version: TariffVersion,
    day: date,
    amount: Money,
    month_so_far: MonthSoFar,
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None = None,
) -> Purchase:
    """The kWh that `amount` (as paid, including VAT) buys on `day`, after the kWh and
    purchases already made in the same calendar month; or a `DomainError` saying why not."""
    one_day = DateRange(start=day, end=day + timedelta(days=1))
    _check(version, one_day, free_basic_eligible)
    _check_purchase(amount, month_so_far)
    match version.billing_policy.block_reset:
        case BlockReset.CALENDAR_MONTH:
            pass  # month_so_far is the calendar month's purchases (calculate_month checks)
        case unknown:  # pragma: no cover  # every member is handled above
            assert_never(unknown)
    vat_rate = vat_table.rate_for(one_day)
    fixed_lines, fixed = _fixed_charges(version, day, month_so_far, vat_table, free_basic_eligible)
    if amount.rand < fixed.rand:
        msg = (
            f"the purchase of R{amount.rand:f} does not cover the month's fixed charges "
            f"of R{fixed.rand:f}, deducted from the first purchase of the month"
        )
        raise PurchaseTooSmallError(msg)
    energy_money = amount - fixed
    segments, kwh = _buy(version, day, month_so_far.kwh, energy_money.rand, vat_rate)
    policy = version.rounding_policy
    statuses = (
        [segment.status for segment in segments]
        + [line.status for line in fixed_lines]
        + [s.kind for s in cited_statuses(_header_values(version))]
        + [s.kind for s in cited_statuses(vat_rate)]
    )
    status = weakest_kind(statuses)
    with exact():
        after = month_so_far.kwh + kwh
    return Purchase(
        day=day,
        amount=amount,
        month_kwh_before=month_so_far.kwh,
        fixed_charges=fixed,
        fixed_lines=tuple(fixed_lines),
        energy_amount=energy_money,
        segments=tuple(segments),
        kwh=kwh,
        month_kwh_after=after,
        vat_rate=vat_rate,
        status=status,
        rounding_policy=policy.name,
        rounding_policy_status=policy.status.kind,
        billing_policy=version.billing_policy.name,
        billing_policy_status=version.billing_policy.status.kind,
        warnings=_warnings(version, status),
    )


def calculate_month(
    version: TariffVersion,
    purchases: Sequence[tuple[date, Money]],
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None = None,
) -> tuple[Purchase, ...]:
    """A calendar month of purchases, in the order made: each one counts the kWh and
    purchases before it in the month."""
    if not purchases:
        return ()
    first_day = purchases[0][0]
    days = [day for day, _ in purchases]
    if any((d.year, d.month) != (first_day.year, first_day.month) for d in days):
        msg = "the purchases must all fall in one calendar month"
        raise PurchasesNotInOneMonthError(msg)
    if days != sorted(days):
        msg = "the purchases must be given in the order they were made"
        raise PurchasesNotInOneMonthError(msg)
    results: list[Purchase] = []
    so_far = MonthSoFar(purchases=0, kwh=Decimal(0))
    for day, amount in purchases:
        purchase = calculate_purchase(
            version, day, amount, so_far, vat_table, free_basic_eligible=free_basic_eligible
        )
        results.append(purchase)
        so_far = MonthSoFar(purchases=so_far.purchases + 1, kwh=purchase.month_kwh_after)
    return tuple(results)


# ----------------------------------------------------------------------------- checks


def _check(version: TariffVersion, one_day: DateRange, free_basic_eligible: bool | None) -> None:
    if not version.covers(one_day):
        msg = "the purchase day is not inside the tariff version's effective range"
        raise PeriodOutsideVersionError(msg)
    check_price_basis(version)
    allocation = version.free_basic_allocation
    if allocation is not None and free_basic_eligible is None:
        msg = (
            "this tariff has a free basic allocation: say whether the customer is eligible "
            "(free_basic_eligible=True or False); it is never assumed"
        )
        raise FreeBasicEligibilityRequiredError(msg)
    if free_basic_eligible:
        msg = "free basic electricity on prepaid meters (free tokens) is not built yet"
        raise PrepaidNotSupportedError(msg)


def _check_purchase(amount: Money, month_so_far: MonthSoFar) -> None:
    if amount.rand < 0:
        msg = "a purchase amount cannot be negative"
        raise InvalidPurchaseError(msg)
    if month_so_far.purchases == 0 and month_so_far.kwh > 0:
        msg = "kWh bought earlier in the month need at least one earlier purchase"
        raise InvalidPurchaseError(msg)


def _header_values(version: TariffVersion) -> list[object]:
    return [getattr(version, name) for name in type(version).model_fields if name != "components"]


# ------------------------------------------------------------------------ fixed charges


def _fixed_charges(
    version: TariffVersion,
    day: date,
    month_so_far: MonthSoFar,
    vat_table: VatTable,
    free_basic_eligible: bool | None,
) -> tuple[list[LineItem], Money]:
    policy = version.billing_policy.prepaid_fixed_charges
    if policy is PrepaidFixedCharges.NOT_FROM_PURCHASES or month_so_far.purchases > 0:
        return [], Money.zero()
    if not any(_is_fixed(component) for component in version.components):
        return [], Money.zero()
    first = day.replace(day=1)
    end = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    month = DateRange(start=first, end=end)
    if not version.covers(month):
        msg = (
            "the month's fixed charges are deducted from its first purchase, but the tariff "
            "version does not cover the whole month"
        )
        raise PeriodOutsideVersionError(msg)
    bill = price_part(
        version,
        month,
        Decimal(0),
        vat_table,
        free_basic_eligible=free_basic_eligible,
        month_fraction=None,
    )
    return list(bill.lines), bill.total


def _is_fixed(component: Component) -> bool:
    if isinstance(component, FixedCharge):
        return True
    return (
        isinstance(component, Levy)
        and component.rate.value.canonical_unit is not CanonicalUnit.RAND_PER_KWH
    )


# ------------------------------------------------------------------------------ energy


def _buy(
    version: TariffVersion, day: date, before: Decimal, money: Decimal, vat_rate: VatRate
) -> tuple[list[PurchaseSegment], Decimal]:
    priced = _per_kwh_components(version, day)
    cuts = sorted({t for _, _, blocks in priced for t in _thresholds(blocks)})
    point = version.rounding_policy.prepaid_kwh
    if point is not None:
        _check_whole_steps(point, before, cuts)
    walk = _Walk(point=point, left=money)
    lower = Decimal(0)
    for upper in cuts:  # bounded segments [lower, upper)
        if upper > before:
            start = max(lower, before)
            price, sources = _price(priced, lower, vat_rate)
            if not walk.fill(start, upper, price, sources):
                return walk.finish(start, upper, price, sources)
        lower = upper
    start = max(lower, before)
    price, sources = _price(priced, lower, vat_rate)
    return walk.finish(start, None, price, sources)


def _check_whole_steps(point: Quantisation, before: Decimal, cuts: list[Decimal]) -> None:
    with exact():
        uneven = [value for value in (before, *cuts) if value % point.step != 0]
    if uneven:
        msg = (
            f"the month's kWh so far and every block threshold must be whole multiples of "
            f"the prepaid kWh step {point.step:f}; {uneven[0]:f} is not"
        )
        raise PrepaidPrecisionError(msg)


class _Walk:
    """The money left and the kWh bought so far, segment by segment."""

    def __init__(self, *, point: Quantisation | None, left: Decimal) -> None:
        self.point = point
        self.left = left
        self.full = Decimal(0)  # kWh bought in whole segments
        self.segments: list[PurchaseSegment] = []

    def fill(
        self, start: Decimal, upper: Decimal, price: Decimal, sources: tuple[Source, ...]
    ) -> bool:
        """Buy the whole segment if the money left covers it; False if it does not."""
        with exact():
            capacity = upper - start
            cost = capacity * price
        if cost > self.left:
            return False
        with exact():
            self.left -= cost
            self.full += capacity
        self.segments.append(_segment(start, upper, capacity, price, cost, sources))
        return True

    def finish(
        self, start: Decimal, upper: Decimal | None, price: Decimal, sources: tuple[Source, ...]
    ) -> tuple[list[PurchaseSegment], Decimal]:
        """Spend what is left in this segment and round the purchase's kWh once."""
        if self.left > 0 and price == 0:
            msg = "the energy is free from here on, so the amount would buy unlimited kWh"
            raise PrepaidNotSupportedError(msg)
        if self.left == 0:
            return self.segments, self._rounded(self.full)
        with exact():
            numerator = self.full * price + self.left
        if self.point is None:
            with exact():
                total = numerator / price
        else:
            total = self.point.divide(numerator, price)
        with exact():
            last = total - self.full
        self.segments.append(_segment(start, upper, last, price, self.left, sources))
        return self.segments, total

    def _rounded(self, kwh: Decimal) -> Decimal:
        return kwh if self.point is None else self.point.apply(kwh)


def _segment(  # one segment's figures
    start: Decimal,
    upper: Decimal | None,
    kwh: Decimal,
    price: Decimal,
    spent: Decimal,
    sources: tuple[Source, ...],
) -> PurchaseSegment:
    return PurchaseSegment(
        from_kwh=start,
        to_kwh=upper,
        kwh=kwh,
        price_per_kwh=price,
        amount=Money.of(spent),
        sources=sources,
        status=weakest_kind(source.status for source in sources),
    )


type _Priced = tuple[Component, VatTreatment, tuple[Block, ...]]


def _per_kwh_components(version: TariffVersion, day: date) -> list[_Priced]:
    """Every component charged per kWh, with its blocks (a flat rate is one open block)."""
    priced: list[_Priced] = []
    for component in version.components:
        if isinstance(component, BlockEnergy):
            priced.append((component, component.vat.value, component.blocks))
        elif isinstance(component, SeasonalEnergy):
            season = next(s for s in component.seasons if s.dates.value.contains(day))
            priced.append((component, component.vat.value, season.blocks))
        elif isinstance(component, FlatEnergy) or (
            isinstance(component, Levy)
            and component.rate.value.canonical_unit is CanonicalUnit.RAND_PER_KWH
        ):
            priced.append(
                (component, component.vat.value, (Block(up_to_kwh=None, rate=component.rate),))
            )
    return priced


def _thresholds(blocks: tuple[Block, ...]) -> list[Decimal]:
    return [block.up_to_kwh.value for block in blocks if block.up_to_kwh is not None]


def _price(
    priced: list[_Priced], low: Decimal, vat_rate: VatRate
) -> tuple[Decimal, tuple[Source, ...]]:
    """The price of one kWh in the segment starting at `low` (including VAT where the
    component is standard-rated), and the sources of every value it used."""
    price = Decimal(0)
    sources: list[Source] = []
    for component, vat, blocks in priced:
        rate, used = _block_at(blocks, low)
        with exact():
            unit = rate.value.canonical_value
            if vat is VatTreatment.STANDARD:
                unit = unit * (1 + vat_rate.fraction)
            price += unit
        sources.extend(_sources(component, rate, used, blocks))
    return price, tuple(sources)


def _block_at(blocks: tuple[Block, ...], low: Decimal) -> tuple[Cited[Rate], int]:
    """The block whose range holds the segment starting at `low` (the last is open)."""
    for index, block in enumerate(blocks[:-1]):
        if block.up_to_kwh is not None and low < block.up_to_kwh.value:
            return block.rate, index
    return blocks[-1].rate, len(blocks) - 1


def _sources(
    component: Component, rate: Cited[Rate], index: int, blocks: tuple[Block, ...]
) -> list[Source]:
    sources = [
        Source(role=SourceRole.RATE, citation=rate.citation, status=rate.kind),
        Source(
            role=SourceRole.LABEL, citation=component.label.citation, status=component.label.kind
        ),
        Source(
            role=SourceRole.VAT_TREATMENT,
            citation=component.vat.citation,
            status=component.vat.kind,
        ),
    ]
    lower = blocks[index - 1].up_to_kwh if index > 0 else None
    upper = blocks[index].up_to_kwh
    for role, threshold in (
        (SourceRole.LOWER_THRESHOLD, lower),
        (SourceRole.UPPER_THRESHOLD, upper),
    ):
        if threshold is not None:
            sources.append(Source(role=role, citation=threshold.citation, status=threshold.kind))
    return sources


# ----------------------------------------------------------------------------- warnings


def _warnings(version: TariffVersion, status: StatusKind) -> tuple[BillWarning, ...]:
    warnings: list[BillWarning] = []
    if status is not StatusKind.VERIFIED:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_VALUES,
                message=(
                    f"Some values used are {status.value.replace('_', '-')}, not verified "
                    "against the source; see each segment's status."
                ),
            )
        )
    rounding = version.rounding_policy
    if rounding.needs_warning:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_ROUNDING_POLICY,
                message=(
                    f"Rounding policy '{rounding.name}' is "
                    f"{rounding.status.kind.value.replace('_', '-')}; the kWh may differ from "
                    "a real receipt in the last digit."
                ),
            )
        )
    billing = version.billing_policy
    if billing.needs_warning:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_BILLING_POLICY,
                message=(
                    f"Billing policy '{billing.name}' (when blocks reset and how fixed charges "
                    "are recovered from purchases) is not verified; a real receipt may differ."
                ),
            )
        )
    return tuple(warnings)
