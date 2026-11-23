"""The forward engine: consumption to cost for one billing period and one tariff version.

Steps (architecture overview, "How a calculation works", for a single version):

1. Refuse what cannot be calculated: an unsupported profile, a period outside the version,
   a period that is not one calendar month when a value is monthly (block thresholds,
   monthly charges and levies, a free allocation that applies; pro-rating is P1-13),
   prices printed including VAT (not built yet), a period without one VAT rate, an
   eligible customer on a tariff without a free basic allocation, a missing eligibility
   input where one is needed, a period across a season boundary of a seasonal component
   or of the time-of-use calendar (`calculate_period` splits), and consumption of the
   wrong shape (`read_consumption`: a period total on a tariff priced by time of use, kWh
   per period on any other, an absent or undefined period, exported kWh until P4-8, use
   in a period the bill's season lacks).
2. Evaluate each component into line items, exactly, then quantise each line if the
   policy names a line-amount point. A free basic allocation, for an eligible customer,
   becomes credit lines that mirror the energy lines of the kWh it makes free.
3. Apply VAT per line or on the subtotal of standard-rated lines, as the policy says.
4. Add up and quantise the total if the policy names a total point.
5. Report the weakest status of every value used and warn about anything not verified.

All arithmetic is exact (`Rate.charge`, `Money`, `exact()`); rounding happens only through
the version's rounding policy. A negative amount (a credit) is rounded as the positive
amount it mirrors, then negated (`Money.quantised`), so a credit cancels its charge
exactly whatever the rounding mode. The work done grows with the number of components
and blocks, never with kWh; days count only through the season lookups, which check at
most 366 days per seasonal component and for the time-of-use calendar, whatever the length
of the period.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from munisense.domain.billing.consumption import (
    PeriodTotal,
    TimeOfUseBuckets,
)
from munisense.domain.billing.errors import (
    FreeBasicEligibilityRequiredError,
    FreeBasicNotOfferedError,
    NonMonthlyPeriodError,
    PeriodCrossesSeasonError,
    PeriodOutsideVersionError,
    UnsupportedConsumptionError,
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
    Block,
    BlockEnergy,
    CalendarSeason,
    Component,
    FixedCharge,
    FlatEnergy,
    FreeBasicAllocation,
    Levy,
    PriceBasis,
    Season,
    SeasonalEnergy,
    TariffVersion,
    TimeOfUseEnergy,
    TouCalendar,
    TouPeriod,
    UndefinedPeriodError,
    VatTreatment,
)


def calculate_bill(
    version: TariffVersion,
    period: DateRange,
    consumption: PeriodTotal | TimeOfUseBuckets,
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None = None,
) -> Bill:
    """Calculate a bill, or raise a `DomainError` explaining why it cannot.

    `free_basic_eligible` says whether the customer qualifies for the tariff's free basic
    allocation. It is an input, never inferred: it must be given (`True` or `False`) for a
    tariff that has an allocation, and `True` is refused for a tariff without one.
    """
    total_kwh, used_by_period = read_consumption(version, consumption)
    _check_calculable(version, period, free_basic_eligible=free_basic_eligible)
    return price_part(
        version,
        period,
        total_kwh,
        vat_table,
        free_basic_eligible=free_basic_eligible,
        month_fraction=None,
        used_by_period=used_by_period,
    )


def read_consumption(
    version: TariffVersion, consumption: PeriodTotal | TimeOfUseBuckets
) -> tuple[Decimal, dict[TouPeriod, Decimal] | None]:
    """The period's total kWh, and its kWh per time-of-use period for a version priced by
    time of use, or a `DomainError` saying why the consumption cannot price this version.

    A version with a time-of-use energy charge needs kWh per period, every period its
    calendar defines given (an absent period is never read as zero use, P4-4); any other
    version needs a period total. Exported kWh are refused until the export credit is
    built (P4-8)."""
    priced_by_period = any(c.needs_calendar for c in version.components)
    if isinstance(consumption, PeriodTotal):
        if priced_by_period:
            msg = "this tariff is priced by time of use: give the kWh used in each period"
            raise UnsupportedConsumptionError(msg)
        return consumption.kwh, None
    if not priced_by_period or version.tou_calendar is None:
        msg = "kWh per time-of-use period price only a tariff priced by time of use"
        raise UnsupportedConsumptionError(msg)
    if consumption.exported_kwh:
        msg = "exported kWh (even 0) cannot be priced until the export credit is built (P4-8)"
        raise UnsupportedConsumptionError(msg)
    calendar = version.tou_calendar
    calendar.require_defined(consumption.used_kwh)
    missing = sorted(calendar.periods - consumption.used_kwh.keys())
    if missing:
        msg = (
            f"give the kWh used in every period the tariff defines (missing: "
            f"{', '.join(missing)}; give 0 for a period with no use)"
        )
        raise UnsupportedConsumptionError(msg)
    used = dict(consumption.used_kwh)
    with exact():
        total = sum(used.values(), Decimal(0))
    return total, used


def price_part(
    version: TariffVersion,
    period: DateRange,
    total_kwh: Decimal,
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None,
    month_fraction: Decimal | None,
    used_by_period: Mapping[TouPeriod, Decimal] | None = None,
) -> Bill:
    """Price one part of a period with one version (used by `calculate_bill` and by period
    splitting). `month_fraction` scales every monthly value (monthly charges and levies,
    block thresholds, a free monthly allocation) for a part of a calendar month; `None`
    means a whole month (or no monthly values). The caller has checked the inputs, except
    for the season, the VAT rate and the eligibility, which are checked here."""
    _check_eligibility(version, free_basic_eligible)
    seasons = _seasons(version, period)
    eligible = bool(free_basic_eligible)
    scale = Decimal(1) if month_fraction is None else month_fraction
    vat_rate = vat_table.rate_for(period)
    policy = version.rounding_policy
    energy = {
        c.name: c
        for c in version.components
        if isinstance(c, FlatEnergy | BlockEnergy | SeasonalEnergy)
    }

    by_period = _time_of_use(version, period, used_by_period)
    lines = [
        _quantise_line(line, policy.line_amount)
        for component in version.components
        for line in _evaluate(
            component, period, total_kwh, energy, seasons, eligible, scale, by_period
        )
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
        free_basic_eligible=free_basic_eligible,
        month_fraction=month_fraction,
        warnings=_warnings(status, policy, credited=_credited(version, lines)),
    )


def _credited(version: TariffVersion, lines: list[LineItem]) -> bool:
    allocation = version.free_basic_allocation
    return allocation is not None and any(line.component == allocation.name for line in lines)


def _header_values(version: TariffVersion) -> list[object]:
    """Every field of the version except its components, so no header value is missed."""
    return [getattr(version, name) for name in type(version).model_fields if name != "components"]


# ----------------------------------------------------------------------------- checks


def _check_calculable(
    version: TariffVersion, period: DateRange, *, free_basic_eligible: bool | None
) -> None:
    _check_eligibility(version, free_basic_eligible)
    if not version.covers(period):
        msg = "the billing period is not wholly inside the tariff version's effective range"
        raise PeriodOutsideVersionError(msg)
    check_price_basis(version)
    monthly = has_monthly_values(version, eligible=bool(free_basic_eligible))
    if monthly and not period.is_whole_calendar_month:
        msg = (
            "this tariff has monthly values (block thresholds, monthly charges or levies, or "
            "a free monthly allocation); a period that is not one calendar month must be "
            "split and pro-rated with calculate_period"
        )
        raise NonMonthlyPeriodError(msg)


def has_monthly_values(version: TariffVersion, *, eligible: bool) -> bool:
    """True when the version has a value given per calendar month for this customer: a
    block threshold, a monthly charge or levy, or a free allocation that applies."""
    return any(_is_monthly(c, eligible) for c in version.components)


def check_price_basis(version: TariffVersion) -> None:
    """Refuse prices printed including VAT, which the engine does not support yet."""
    if version.price_basis.value is not PriceBasis.EXCLUDING_VAT:
        msg = "prices printed including VAT are not supported yet"
        raise UnsupportedPriceBasisError(msg)


def _check_eligibility(version: TariffVersion, free_basic_eligible: bool | None) -> None:
    if free_basic_eligible and version.free_basic_allocation is None:
        msg = "the customer is marked eligible for a free basic allocation this tariff lacks"
        raise FreeBasicNotOfferedError(msg)
    if free_basic_eligible is None and version.free_basic_allocation is not None:
        msg = (
            "this tariff has a free basic allocation: say whether the customer is eligible "
            "(free_basic_eligible=True or False); it is never assumed"
        )
        raise FreeBasicEligibilityRequiredError(msg)


def _seasons(version: TariffVersion, period: DateRange) -> dict[str, Season]:
    """The season each seasonal component uses for the period; refuses a period that
    crosses a season boundary (`calculate_period` splits such periods first)."""
    last_day = period.end - timedelta(days=1)
    seasons: dict[str, Season] = {}
    for component in version.components:
        if isinstance(component, SeasonalEnergy):
            season = component.season_for(period.start, last_day)
            if season is None:
                msg = (
                    f"the billing period crosses a season boundary of '{component.name}'; "
                    "splitting a period into seasons is not built yet"
                )
                raise PeriodCrossesSeasonError(msg)
            seasons[component.name] = season
    return seasons


@dataclass(frozen=True)
class _TouPart:
    """The calendar season a part lies in, and its kWh per period."""

    season: CalendarSeason
    used: Mapping[TouPeriod, Decimal]


def _time_of_use(
    version: TariffVersion, period: DateRange, used: Mapping[TouPeriod, Decimal] | None
) -> _TouPart | None:
    """The part's calendar season and kWh per period, for a version priced by time of use;
    refuses a part across a calendar season boundary (`calculate_period` splits first) and
    use in a period the part's season does not have."""
    calendar = version.tou_calendar
    if calendar is None or not any(c.needs_calendar for c in version.components):
        return None  # not priced by time of use, even with a calendar for its seasons
    if used is None:  # pragma: no cover - read_consumption refuses this first
        msg = "this tariff is priced by time of use: give the kWh used in each period"
        raise UnsupportedConsumptionError(msg)
    first = calendar.season_for(period.start).name
    if len(calendar.seasons) > 1 and _crosses_a_season(calendar, period):
        msg = (
            "the billing period crosses a season boundary of the time-of-use calendar; "
            "split it with calculate_period"
        )
        raise PeriodCrossesSeasonError(msg)
    unused = sorted(p for p, kwh in used.items() if kwh > 0 and p not in calendar.periods_in(first))
    if unused:
        msg = f"kWh are given for {', '.join(unused)}, which the {first} season does not have"
        raise UndefinedPeriodError(msg)
    return _TouPart(calendar.season_for(period.start), used)


def _crosses_a_season(calendar: TouCalendar, period: DateRange) -> bool:
    """True when some day of the period is in another season than its first day. With two
    or more seasons, each is shorter than a year, so a period of more than 366 days always
    crosses; otherwise at most 366 days are checked (the bounded work above)."""
    if period.days > 366:
        return True
    first = calendar.season_for(period.start).name
    days = (period.start + timedelta(days=n) for n in range(period.days))
    return any(calendar.season_for(day).name != first for day in days)


def _is_monthly(component: Component, free_basic_eligible: bool) -> bool:
    if isinstance(component, BlockEnergy):
        return True
    if isinstance(component, SeasonalEnergy):
        return component.has_thresholds
    if isinstance(component, FreeBasicAllocation):
        return free_basic_eligible  # only applies, and so only matters, when eligible
    return (
        isinstance(component, FixedCharge | Levy)
        and component.rate.value.canonical_unit is CanonicalUnit.RAND_PER_MONTH
    )


# ------------------------------------------------------------------------- components


def _evaluate(
    component: Component,
    period: DateRange,
    kwh: Decimal,
    energy: dict[str, FlatEnergy | BlockEnergy | SeasonalEnergy],
    seasons: dict[str, Season],
    free_basic_eligible: bool,
    scale: Decimal,
    by_period: _TouPart | None,
) -> Iterator[LineItem]:
    if isinstance(component, TimeOfUseEnergy):
        if by_period is None:  # pragma: no cover - _time_of_use refuses this first
            raise AssertionError
        yield from _time_of_use_lines(component, by_period)
    elif isinstance(component, FixedCharge):
        yield _fixed(component, period, scale)
    elif isinstance(component, Levy):
        if component.rate.value.canonical_unit is not CanonicalUnit.RAND_PER_KWH:
            yield _fixed(component, period, scale)
        elif kwh > 0:
            yield _line(component, "all kWh", kwh, QuantityUnit.KWH, component.rate)
    elif isinstance(component, FreeBasicAllocation):
        if free_basic_eligible:
            target = energy[component.energy_component]
            yield from _free_basic(component, target, kwh, seasons, scale)
    else:
        yield from _energy(component, kwh, seasons, scale)


def _energy(
    component: FlatEnergy | BlockEnergy | SeasonalEnergy,
    kwh: Decimal,
    seasons: dict[str, Season],
    scale: Decimal,
) -> Iterator[LineItem]:
    if isinstance(component, BlockEnergy):
        yield from _blocks(component, component.blocks, kwh, scale=scale)
    elif isinstance(component, SeasonalEnergy):
        yield from _seasonal(component, seasons[component.name], kwh, scale)
    elif kwh > 0:
        yield _line(component, "all kWh", kwh, QuantityUnit.KWH, component.rate)


def _time_of_use_lines(component: TimeOfUseEnergy, part: _TouPart) -> Iterator[LineItem]:
    """One line per period with use, at that period's rate in the part's season."""
    season = part.season
    extra = (
        Source(role=SourceRole.SEASON, citation=season.dates.citation, status=season.dates.kind),
        Source(
            role=SourceRole.SEASON_LABEL, citation=season.label.citation, status=season.label.kind
        ),
    )
    for period in TouPeriod:
        kwh = part.used.get(period, Decimal(0))
        if kwh > 0:
            rate = component.rate_for(season.name, period)
            description = f"{season.label.value}: {period.value.replace('_', '-')} kWh"
            yield _line(component, description, kwh, QuantityUnit.KWH, rate, extra=extra)


def _seasonal(
    component: SeasonalEnergy, season: Season, kwh: Decimal, scale: Decimal
) -> Iterator[LineItem]:
    dates, label = season.dates, season.label
    extra = (
        Source(role=SourceRole.SEASON, citation=dates.citation, status=dates.kind),
        Source(role=SourceRole.SEASON_LABEL, citation=label.citation, status=label.kind),
    )
    prefix = f"{season.label.value}: "
    if len(season.blocks) == 1:  # one open block: a flat rate for the season
        if kwh > 0:
            rate = season.blocks[0].rate
            yield _line(component, f"{prefix}all kWh", kwh, QuantityUnit.KWH, rate, extra=extra)
    else:
        yield from _blocks(component, season.blocks, kwh, prefix=prefix, extra=extra, scale=scale)


def _free_basic(
    allocation: FreeBasicAllocation,
    target: FlatEnergy | BlockEnergy | SeasonalEnergy,
    kwh: Decimal,
    seasons: dict[str, Season],
    scale: Decimal,
) -> Iterator[LineItem]:
    """Credit lines for the free kWh: the target's lines for the first `free` kWh, negated,
    citing the allocation's label, VAT treatment and free kWh as well as the target's rate
    and thresholds."""
    with exact():
        free = min(kwh, allocation.free_kwh.value * scale)
    for charge in _energy(target, free, seasons, scale):
        sources = (
            *(
                s
                for s in charge.sources
                if s.role not in {SourceRole.LABEL, SourceRole.VAT_TREATMENT}
            ),
            Source(
                role=SourceRole.LABEL,
                citation=allocation.label.citation,
                status=allocation.label.kind,
            ),
            Source(
                role=SourceRole.VAT_TREATMENT,
                citation=allocation.vat.citation,
                status=allocation.vat.kind,
            ),
            Source(
                role=SourceRole.FREE_ALLOWANCE,
                citation=allocation.free_kwh.citation,
                status=allocation.free_kwh.kind,
            ),
        )
        yield LineItem(
            component=allocation.name,
            label=allocation.label.value,
            description=f"free: {charge.description}",
            quantity=charge.quantity,
            unit=charge.unit,
            rate=charge.rate,
            amount=Money.zero() - charge.amount,
            vat_treatment=allocation.vat.value,
            vat=None,
            sources=sources,
            status=weakest_kind(source.status for source in sources),
        )


def _fixed(component: FixedCharge | Levy, period: DateRange, scale: Decimal) -> LineItem:
    if component.rate.value.canonical_unit is CanonicalUnit.RAND_PER_DAY:
        days = Decimal(period.days)
        return _line(component, f"{period.days} days", days, QuantityUnit.DAY, component.rate)
    if scale == 1:
        return _line(component, "1 month", Decimal(1), QuantityUnit.MONTH, component.rate)
    description = f"{period.days} days of the month, pro-rated: {scale:f} of a month"
    return _line(component, description, scale, QuantityUnit.MONTH, component.rate)


def _blocks(
    component: BlockEnergy | SeasonalEnergy,
    blocks: tuple[Block, ...],
    kwh: Decimal,
    *,
    prefix: str = "",
    extra: tuple[Source, ...] = (),
    scale: Decimal,
) -> Iterator[LineItem]:
    """Lines for the blocks used; thresholds are per calendar month, so for part of a month
    they are scaled by the month fraction (`scale`)."""
    previous: Cited[ExactDecimal] | None = None
    lower = Decimal(0)
    for number, block in enumerate(blocks, start=1):
        with exact():
            upper = None if block.up_to_kwh is None else block.up_to_kwh.value * scale
            used = max(Decimal(0), (kwh if upper is None else min(kwh, upper)) - lower)
        if used > 0:
            span = f"above {lower:f} kWh" if upper is None else f"{lower:f} to {upper:f} kWh"
            yield _line(
                component,
                f"{prefix}block {number}: {span}",
                used,
                QuantityUnit.KWH,
                block.rate,
                lower_threshold=previous,
                upper_threshold=block.up_to_kwh,
                extra=extra,
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
    extra: tuple[Source, ...] = (),
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
    sources = (*(Source(role=r, citation=c, status=k) for r, c, k in roles), *extra)
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
    """Round at a policy point (`Money.quantised` rounds a credit by its magnitude)."""
    return amount if point is None else amount.quantised(point)


def _quantise_line(line: LineItem, point: Quantisation | None) -> LineItem:
    if point is None:
        return line
    return LineItem.model_validate(line.model_dump() | {"amount": _quantised(line.amount, point)})


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


def _warnings(
    status: StatusKind, policy: RoundingPolicy, *, credited: bool
) -> tuple[BillWarning, ...]:
    warnings: list[BillWarning] = []
    if credited:
        warnings.append(
            BillWarning(
                code=WarningCode.ASSUMED_FREE_BASIC_METHOD,
                message=(
                    "The free basic allocation is applied by crediting the first free kWh at "
                    "the energy's own rates, block by block; the supplier's method is not "
                    "confirmed."
                ),
            )
        )
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
