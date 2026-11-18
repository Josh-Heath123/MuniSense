"""The forward engine: consumption to cost for one billing period and one tariff version.

Steps (architecture overview, "How a calculation works", for a single version):

1. Refuse what cannot be calculated: an unsupported profile, a period outside the version,
   a period that is not one calendar month when a value is monthly (block thresholds and
   monthly charges; pro-rating is P1-13), prices printed including VAT (not built yet), and
   a period without one VAT rate.
2. Evaluate each component into line items, exactly, then quantise each line if the
   policy names a line-amount point.
3. Apply VAT per line or on the subtotal of standard-rated lines, as the policy says.
4. Add up and quantise the total if the policy names a total point.
5. Report the weakest status of every value used and warn about anything not verified.

All arithmetic is exact (`Rate.charge`, `Money`, `exact()`); rounding happens only through
the version's rounding policy. The work done grows with the number of components and
blocks, never with the number of days or kWh.
"""

from collections.abc import Iterator
from decimal import Decimal

from munisense.domain.billing.consumption import (
    PeriodTotal,
    TimeOfUseBuckets,
    require_period_total,
)
from munisense.domain.billing.errors import (
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
    UnsupportedPriceBasisError,
)
from munisense.domain.billing.result import (
    Bill,
    BillWarning,
    LineItem,
    QuantityUnit,
    Source,
    SourceRole,
    WarningCode,
)
from munisense.domain.citations import Cited, StatusKind, cited_statuses, weakest_kind
from munisense.domain.money import (
    CanonicalUnit,
    ExactDecimal,
    Money,
    Quantisation,
    Rate,
    RoundingPolicy,
    VatApplication,
    VatRate,
    VatTable,
    exact,
)
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import (
    BlockEnergy,
    Component,
    FixedCharge,
    FlatEnergy,
    PriceBasis,
    TariffVersion,
    VatTreatment,
)


def calculate_bill(
    version: TariffVersion,
    period: DateRange,
    consumption: PeriodTotal | TimeOfUseBuckets,
    vat_table: VatTable,
) -> Bill:
    """Calculate a bill, or raise a `DomainError` explaining why it cannot."""
    total_kwh = require_period_total(consumption).kwh
    _check_calculable(version, period)
    vat_rate = vat_table.rate_for(period)
    policy = version.rounding_policy

    lines = [
        _quantise_line(line, policy.line_amount)
        for component in version.components
        for line in _evaluate(component, period, total_kwh)
    ]
    lines, vat = _apply_vat(lines, vat_rate, policy)
    subtotal = Money.sum(line.amount for line in lines)
    total = _quantised(subtotal + vat, policy.total)

    status = weakest_kind(
        [line.status for line in lines]
        + [s.kind for s in cited_statuses(_header_values(version))]
        + [s.kind for s in cited_statuses(vat_rate)]
    )
    end = version.effective_to
    return Bill(
        supplier=version.supplier,
        tariff_code=version.tariff_code,
        tariff_name=version.printed_name.value,
        version_effective_from=version.effective_from.value,
        version_effective_to=None if end is None else end.value,
        period=period,
        consumption_kwh=total_kwh,
        lines=tuple(lines),
        subtotal=subtotal,
        vat_rate=vat_rate,
        vat=vat,
        total=total,
        status=status,
        rounding_policy=policy.name,
        rounding_policy_status=policy.status.kind,
        warnings=_warnings(status, policy),
    )


def _header_values(version: TariffVersion) -> list[object]:
    """Every field of the version except its components, so no header value is missed."""
    return [getattr(version, name) for name in type(version).model_fields if name != "components"]


# ----------------------------------------------------------------------------- checks


def _check_calculable(version: TariffVersion, period: DateRange) -> None:
    if not version.covers(period):
        msg = "the billing period is not wholly inside the tariff version's effective range"
        raise PeriodOutsideVersionError(msg)
    if version.price_basis.value is not PriceBasis.EXCLUDING_VAT:
        msg = "prices printed including VAT are not supported yet"
        raise UnsupportedPriceBasisError(msg)
    if not period.is_whole_calendar_month and any(_is_monthly(c) for c in version.components):
        msg = (
            "this tariff has monthly values (block thresholds or monthly charges); a period "
            "that is not one calendar month needs a pro-rating policy, which is not built yet"
        )
        raise NonMonthlyPeriodError(msg)


def _is_monthly(component: Component) -> bool:
    if isinstance(component, BlockEnergy):
        return True
    return (
        isinstance(component, FixedCharge)
        and component.rate.value.canonical_unit is CanonicalUnit.RAND_PER_MONTH
    )


# ------------------------------------------------------------------------- components


def _evaluate(component: Component, period: DateRange, kwh: Decimal) -> Iterator[LineItem]:
    if isinstance(component, FixedCharge):
        yield _fixed(component, period)
    elif isinstance(component, FlatEnergy):
        if kwh > 0:
            yield _line(component, "all kWh", kwh, QuantityUnit.KWH, component.rate)
    else:
        yield from _blocks(component, kwh)


def _fixed(component: FixedCharge, period: DateRange) -> LineItem:
    if component.rate.value.canonical_unit is CanonicalUnit.RAND_PER_DAY:
        days = Decimal(period.days)
        return _line(component, f"{period.days} days", days, QuantityUnit.DAY, component.rate)
    return _line(component, "1 month", Decimal(1), QuantityUnit.MONTH, component.rate)


def _blocks(component: BlockEnergy, kwh: Decimal) -> Iterator[LineItem]:
    previous: Cited[ExactDecimal] | None = None
    lower = Decimal(0)
    for number, block in enumerate(component.blocks, start=1):
        upper = None if block.up_to_kwh is None else block.up_to_kwh.value
        with exact():
            used = max(Decimal(0), (kwh if upper is None else min(kwh, upper)) - lower)
        if used > 0:
            span = f"above {lower:f} kWh" if upper is None else f"{lower:f} to {upper:f} kWh"
            yield _line(
                component,
                f"block {number}: {span}",
                used,
                QuantityUnit.KWH,
                block.rate,
                lower_threshold=previous,
                upper_threshold=block.up_to_kwh,
            )
        previous = block.up_to_kwh
        lower = upper if upper is not None else lower


def _line(
    component: Component,
    description: str,
    quantity: Decimal,
    unit: QuantityUnit,
    rate: Cited[Rate],
    *,
    lower_threshold: Cited[ExactDecimal] | None = None,
    upper_threshold: Cited[ExactDecimal] | None = None,
) -> LineItem:
    roles = [
        (SourceRole.RATE, rate.citation, rate.kind),
        (SourceRole.LABEL, component.label.citation, component.label.kind),
        (SourceRole.VAT_TREATMENT, component.vat.citation, component.vat.kind),
    ]
    for role, threshold in (
        (SourceRole.LOWER_THRESHOLD, lower_threshold),
        (SourceRole.UPPER_THRESHOLD, upper_threshold),
    ):
        if threshold is not None:
            roles.append((role, threshold.citation, threshold.kind))
    sources = tuple(Source(role=r, citation=c, status=k) for r, c, k in roles)
    return LineItem(
        component=component.name,
        label=component.label.value,
        description=description,
        quantity=quantity,
        unit=unit,
        rate=rate.value,
        amount=rate.value.charge(quantity),
        vat_treatment=component.vat.value,
        vat=None,
        sources=sources,
        status=weakest_kind(source.status for source in sources),
    )


# ------------------------------------------------------------------- rounding and VAT


def _quantised(amount: Money, point: Quantisation | None) -> Money:
    return amount if point is None else amount.quantised(point)


def _quantise_line(line: LineItem, point: Quantisation | None) -> LineItem:
    if point is None:
        return line
    return LineItem.model_validate(line.model_dump() | {"amount": line.amount.quantised(point)})


def _apply_vat(
    lines: list[LineItem], vat_rate: VatRate, policy: RoundingPolicy
) -> tuple[list[LineItem], Money]:
    taxable = [line.vat_treatment is VatTreatment.STANDARD for line in lines]
    if policy.vat_application is VatApplication.PER_LINE:
        with_vat = [
            LineItem.model_validate(
                line.model_dump()
                | {
                    "vat": _quantised(line.amount * vat_rate.fraction, policy.vat_amount)
                    if is_taxable
                    else Money.zero()
                }
            )
            for line, is_taxable in zip(lines, taxable, strict=True)
        ]
        return with_vat, Money.sum(line.vat or Money.zero() for line in with_vat)
    base = Money.sum(
        line.amount for line, is_taxable in zip(lines, taxable, strict=True) if is_taxable
    )
    return lines, _quantised(base * vat_rate.fraction, policy.vat_amount)


# --------------------------------------------------------------------------- warnings


def _words(kind: StatusKind) -> str:
    return kind.value.replace("_", "-")


def _warnings(status: StatusKind, policy: RoundingPolicy) -> tuple[BillWarning, ...]:
    warnings: list[BillWarning] = []
    if status is not StatusKind.VERIFIED:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_VALUES,
                message=(
                    f"Some values used are {_words(status)}, not verified "
                    "against the source; see each line's status."
                ),
            )
        )
    if policy.needs_warning:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_ROUNDING_POLICY,
                message=(
                    f"Rounding policy '{policy.name}' is {_words(policy.status.kind)}; "
                    "cent-level differences from a real bill are possible."
                ),
            )
        )
    return tuple(warnings)
