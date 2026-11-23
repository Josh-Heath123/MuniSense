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
   per period on any other, an absent or undefined period, exported kWh on a tariff
   without an export credit, use in a period the bill's season lacks), and exports on a
   period that is not whole calendar months (the cap is per month, P4-8).
2. Evaluate each component into line items, exactly, then quantise each line if the
   policy names a line-amount point. A free basic allocation, for an eligible customer,
   becomes credit lines that mirror the energy lines of the kWh it makes free.
3. Apply VAT per line or on the subtotal of standard-rated lines, as the policy says.
4. Add up and quantise the total if the policy names a total point; refuse a negative
   total (an export credit larger than the bill: P4-8).
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
from typing import assert_never

from munisense.domain.billing.consumption import (
    PeriodTotal,
    TimeOfUseBuckets,
)
from munisense.domain.billing.errors import (
    FreeBasicEligibilityRequiredError,
    FreeBasicNotOfferedError,
    MissingQuantityError,
    NegativeBillError,
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
    BillingPolicy,
    Block,
    BlockEnergy,
    CalendarSeason,
    Component,
    ExportCap,
    ExportCredit,
    FixedCharge,
    FlatEnergy,
    FreeBasicAllocation,
    Levy,
    PriceBasis,
    Quantity,
    QuantityCharge,
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
    quantities: Mapping[Quantity, Decimal] | None = None,
) -> Bill:
    """Calculate a bill, or raise a `DomainError` explaining why it cannot.

    `free_basic_eligible` says whether the customer qualifies for the tariff's free basic
    allocation. It is an input, never inferred: it must be given (`True` or `False`) for a
    tariff that has an allocation, and `True` is refused for a tariff without one.
    `quantities` are the customer's quantities for the month (a maximum demand or a
    capacity, in kVA) that the tariff's quantity charges are priced on (P4-9).
    """
    total_kwh, used_by_period, exported_by_period = read_consumption(version, consumption)
    check_quantities([version], quantities)
    _check_calculable(version, period, free_basic_eligible=free_basic_eligible)
    return price_part(
        version,
        period,
        total_kwh,
        vat_table,
        free_basic_eligible=free_basic_eligible,
        month_fraction=None,
        used_by_period=used_by_period,
        exported_by_period=exported_by_period,
        quantities=quantities,
    )


def prices_by_period(version: TariffVersion) -> bool:
    """True when the version prices kWh per time-of-use period (a time-of-use energy charge
    or an export credit). A quantity charge limited to seasons needs the calendar too, but
    does not price kWh per period."""
    return any(isinstance(c, TimeOfUseEnergy | ExportCredit) for c in version.components)


def check_quantities(
    versions: list[TariffVersion], quantities: Mapping[Quantity, Decimal] | None
) -> None:
    """Every quantity the versions' quantity charges are priced on is given, none is
    negative, and none is given that no charge uses (it would be silently ignored)."""
    given = dict(quantities or {})
    needed = {c.quantity for v in versions for c in v.components if isinstance(c, QuantityCharge)}
    missing = sorted(needed - given.keys())
    if missing:
        msg = f"give the customer's {missing[0].replace('_', ' ')} for the month"
        raise MissingQuantityError(msg)
    unused = sorted(given.keys() - needed)
    if unused:
        msg = f"the tariff has no charge on the {unused[0].replace('_', ' ')}"
        raise MissingQuantityError(msg)
    for value in given.values():
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            msg = "a quantity must be a non-negative exact decimal"
            raise MissingQuantityError(msg)


def read_consumption(
    version: TariffVersion, consumption: PeriodTotal | TimeOfUseBuckets
) -> tuple[Decimal, dict[TouPeriod, Decimal] | None, dict[TouPeriod, Decimal] | None]:
    """The period's total kWh used, and for a version priced by time of use its kWh used
    and exported per period, or a `DomainError` saying why the consumption cannot price
    this version.

    A version priced by time of use needs kWh per period, every period its calendar defines
    given (an absent period is never read as zero use, P4-4); any other version needs a
    period total. Exported kWh price only a version with an export credit; a period absent
    from the exports exported nothing (export is optional, P4-4)."""
    priced_by_period = prices_by_period(version)
    if isinstance(consumption, PeriodTotal):
        if priced_by_period:
            msg = "this tariff is priced by time of use: give the kWh used in each period"
            raise UnsupportedConsumptionError(msg)
        return consumption.kwh, None, None
    if not priced_by_period or version.tou_calendar is None:
        msg = "kWh per time-of-use period price only a tariff priced by time of use"
        raise UnsupportedConsumptionError(msg)
    has_credit = any(isinstance(c, ExportCredit) for c in version.components)
    if consumption.exported_kwh and not has_credit:
        msg = "this tariff has no export credit, so exported kWh (even 0) cannot be priced"
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
    return total, used, dict(consumption.exported_kwh)


def price_part(
    version: TariffVersion,
    period: DateRange,
    total_kwh: Decimal,
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None,
    month_fraction: Decimal | None,
    used_by_period: Mapping[TouPeriod, Decimal] | None = None,
    exported_by_period: Mapping[TouPeriod, Decimal] | None = None,
    quantities: Mapping[Quantity, Decimal] | None = None,
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

    by_period = _time_of_use(version, period, used_by_period, exported_by_period)
    calendar_season = _calendar_season(version, period)
    lines = [
        _quantise_line(line, policy.line_amount)
        for component in version.components
        for line in (
            _quantity_lines(component, quantities or {}, calendar_season, scale)
            if isinstance(component, QuantityCharge)
            else _evaluate(
                component, period, total_kwh, energy, seasons, eligible, scale, by_period
            )
        )
    ]
    lines, vat = _apply_vat(lines, vat_rate, policy)
    subtotal = Money.sum(line.amount for line in lines)
    total = _quantised(subtotal + vat, policy.total)
    if total.rand < 0:
        msg = (
            "the bill would be negative; how the supplier treats a negative bill is not "
            "known, so it is refused"
        )
        raise NegativeBillError(msg)

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
        warnings=_warnings(
            status,
            policy,
            credited=_credited(version, lines),
            exported=version.billing_policy if _export_credited(version, lines) else None,
        ),
    )


def _export_credited(version: TariffVersion, lines: list[LineItem]) -> bool:
    credits = {c.name for c in version.components if isinstance(c, ExportCredit)}
    return any(line.component in credits for line in lines)


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
    exported: Mapping[TouPeriod, Decimal]


def _time_of_use(
    version: TariffVersion,
    period: DateRange,
    used: Mapping[TouPeriod, Decimal] | None,
    exported: Mapping[TouPeriod, Decimal] | None = None,
) -> _TouPart | None:
    """The part's calendar season and kWh per period, for a version priced by time of use;
    refuses a part across a calendar season boundary (`calculate_period` splits first) and
    use in a period the part's season does not have."""
    calendar = version.tou_calendar
    if calendar is None or not prices_by_period(version):
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
    exported = exported or {}
    if any(kwh > 0 for kwh in exported.values()):
        _check_export_cap(version)
    if any(kwh > 0 for kwh in exported.values()) and not period.is_whole_calendar_month:
        msg = (
            "export credits are capped per calendar month, so a bill with exported kWh "
            "must cover whole calendar months"
        )
        raise NonMonthlyPeriodError(msg)
    return _TouPart(calendar.season_for(period.start), used, exported)


def _calendar_season(version: TariffVersion, period: DateRange) -> CalendarSeason | None:
    """The calendar season of a part, for a version with a quantity charge limited to
    seasons; refuses a part across a season boundary (`calculate_period` splits first)."""
    calendar = version.tou_calendar
    limited = any(isinstance(c, QuantityCharge) and c.seasons for c in version.components)
    if calendar is None or not limited:
        return None
    if len(calendar.seasons) > 1 and _crosses_a_season(calendar, period):
        msg = (
            "the billing period crosses a season boundary of the time-of-use calendar; "
            "split it with calculate_period"
        )
        raise PeriodCrossesSeasonError(msg)
    return calendar.season_for(period.start)


def _quantity_lines(
    component: QuantityCharge,
    quantities: Mapping[Quantity, Decimal],
    season: CalendarSeason | None,
    scale: Decimal,
) -> Iterator[LineItem]:
    """The charge for the month (pro-rated like any monthly value): the customer's quantity
    x the rate, only in the seasons it is limited to."""
    if component.seasons and (season is None or season.name not in component.seasons):
        return
    quantity = quantities[component.quantity]
    with exact():
        kva_months = quantity * scale
    name = component.quantity.value.replace("_", " ").replace(" kva", "")
    during = (
        f", in {' and '.join(p.value.replace('_', '-') for p in component.periods)} periods"
        if component.periods
        else ""
    )
    months = "1 month" if scale == 1 else f"{scale:f} of a month"
    description = f"{name} {quantity:f} kVA{during}, {months}"
    extra: tuple[Source, ...] = ()
    if season is not None and component.seasons:
        extra = (
            Source(
                role=SourceRole.SEASON, citation=season.dates.citation, status=season.dates.kind
            ),
        )
    yield _line(
        component, description, kva_months, QuantityUnit.KVA_MONTH, component.rate, extra=extra
    )


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
    if isinstance(component, BlockEnergy | QuantityCharge):
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
    elif isinstance(component, ExportCredit):
        if by_period is None:  # pragma: no cover - _time_of_use refuses this first
            raise AssertionError
        yield from _export_lines(component, by_period)
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
    elif isinstance(component, QuantityCharge):  # pragma: no cover - priced by price_part
        raise AssertionError
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


def _check_export_cap(version: TariffVersion) -> None:
    """The only cap built is per period and calendar month; a new member must be priced
    here before it can be used."""
    cap = version.billing_policy.export_cap
    match cap:
        case ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH:
            return
        case None:  # pragma: no cover - the version refuses a credit without a cap
            raise AssertionError
        case _:  # pragma: no cover - every member is handled above
            assert_never(cap)


def _export_lines(component: ExportCredit, part: _TouPart) -> Iterator[LineItem]:
    """One credit (negative) line per period with export: the kWh credited are the kWh
    exported, capped by the kWh used in the same period (the billing policy's export cap,
    checked to be per calendar month)."""
    season = part.season
    extra = (
        Source(role=SourceRole.SEASON, citation=season.dates.citation, status=season.dates.kind),
        Source(
            role=SourceRole.SEASON_LABEL, citation=season.label.citation, status=season.label.kind
        ),
    )
    for period in TouPeriod:
        with exact():
            credited = min(part.exported.get(period, Decimal(0)), part.used.get(period, Decimal(0)))
        if credited > 0:
            rate = component.rate_for(season.name, period)
            name = period.value.replace("_", "-")
            charge = _line(
                component,
                f"{season.label.value}: {name} kWh exported, credited",
                credited,
                QuantityUnit.KWH,
                rate,
                extra=extra,
            )
            yield LineItem.model_validate(
                charge.model_dump() | {"amount": Money.zero() - charge.amount}
            )


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
    status: StatusKind,
    policy: RoundingPolicy,
    *,
    credited: bool,
    exported: BillingPolicy | None = None,
) -> tuple[BillWarning, ...]:
    """`exported` is the billing policy whose export cap was applied, if any credit was."""
    warnings: list[BillWarning] = []
    if exported is not None and exported.needs_warning:
        warnings.append(
            BillWarning(
                code=WarningCode.UNVERIFIED_EXPORT_CAP,
                message=(
                    f"Exports are credited under billing policy '{exported.name}', which is not "
                    "verified: at most the kWh used in the same time-of-use period, reading "
                    '"each month" as the calendar month.'
                ),
            )
        )
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
