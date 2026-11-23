"""Period splitting (P1-13, ADR-0011): a billing period across calendar months, tariff
versions, seasons or VAT rates, priced part by part.

1. Check the versions: one supplier and tariff, not overlapping, prices excluding VAT.
2. Split the period at every calendar-month start, version change, season start and VAT
   change inside it. Every part must lie inside one version; a day with none is refused.
3. Share the kWh by days (the billing policy's `consumption_split`): each part ends at a
   cumulative factor, days so far / days in the period, rounded at the rounding policy's
   `pro_rating` point; a part's kWh are the difference of two cumulative shares. The shares
   never go negative and always add up to the period's kWh exactly. For a tariff priced by
   time of use, each period's kWh are shared this way on their own (with the same factors,
   so a part's total equals the share of the period total); sharing across a change of
   calendar season always warns, because a supplier bills each season's metered use.
4. Price each part with its own version (`price_part`). A part that is not a whole
   calendar month has its monthly values scaled by days in the part / days in its month,
   rounded at the same point (the billing policy's `pro_rating`).
5. The period's subtotal, VAT and total are the sums of the parts'; its status is the
   weakest of the parts'; it warns about anything not verified, including the billing
   policy whenever a period is split or pro-rated.

The kWh and factors use the policies of the version that covers the period's first day,
so one rounding applies to the whole share-out.
"""

import calendar
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import assert_never

from munisense.domain.billing.consumption import PeriodTotal, TimeOfUseBuckets
from munisense.domain.billing.engine import (
    check_price_basis,
    has_monthly_values,
    price_part,
    read_consumption,
)
from munisense.domain.billing.errors import (
    IncompatibleVersionsError,
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
)
from munisense.domain.billing.result import (
    Bill,
    BillWarning,
    PeriodBill,
    WarningCode,
)
from munisense.domain.citations import weakest_kind
from munisense.domain.money import Money, Quantisation, VatTable, exact
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import (
    BillingPolicy,
    ConsumptionSplit,
    ProRating,
    SeasonalEnergy,
    SeasonDates,
    TariffVersion,
    TouPeriod,
    UndefinedPeriodError,
)


def calculate_period(
    versions: Sequence[TariffVersion],
    period: DateRange,
    consumption: PeriodTotal | TimeOfUseBuckets,
    vat_table: VatTable,
    *,
    free_basic_eligible: bool | None = None,
) -> PeriodBill:
    """Price a period that may span months, versions, seasons and VAT rates, or raise a
    `DomainError` explaining why it cannot."""
    ordered = _check_versions(versions)
    parts = _split(ordered, period, vat_table)
    pricing = list(dict.fromkeys(version for _, version in parts))
    readings = [read_consumption(version, consumption) for version in pricing]
    total_kwh, used, exported = readings[0]  # every version that prices a part accepts it
    ranges = [part for part, _ in parts]
    if used is not None and len(_calendar_seasons(parts)) > 1:
        _check_each_season_has_the_periods(parts, used)
    if exported and any(kwh > 0 for kwh in exported.values()) and len(parts) > 1:
        msg = (
            "exported kWh can be credited only on a bill of one calendar month: the credit is "
            "capped by each month's use, which shared-out figures cannot show; give one bill "
            "per month"
        )
        raise NonMonthlyPeriodError(msg)
    if used is None:
        shares = _shares(total_kwh, period, ranges, parts[0][1])
        by_period: list[dict[TouPeriod, Decimal] | None] = [None] * len(parts)
        exports: list[dict[TouPeriod, Decimal] | None] = [None] * len(parts)
    else:
        # Each period's kWh are shared on their own; a part's total is the sum of its
        # periods' shares, so the two always agree.
        per_period = {p: _shares(kwh, period, ranges, parts[0][1]) for p, kwh in used.items()}
        by_period = [{p: per_period[p][i] for p in used} for i in range(len(parts))]
        out = {p: _shares(kwh, period, ranges, parts[0][1]) for p, kwh in (exported or {}).items()}
        exports = [{p: out[p][i] for p in out} for i in range(len(parts))]
        with exact():
            shares = [sum(part.values(), Decimal(0)) for part in by_period if part is not None]
    eligible = bool(free_basic_eligible)
    bills = [
        price_part(
            version,
            part,
            kwh,
            vat_table,
            free_basic_eligible=free_basic_eligible,
            month_fraction=_month_fraction(part, version, eligible=eligible),
            used_by_period=part_used,
            exported_by_period=part_exported,
        )
        for (part, version), kwh, part_used, part_exported in zip(
            parts, shares, by_period, exports, strict=True
        )
    ]
    split = len(bills) > 1 or any(bill.month_fraction is not None for bill in bills)
    across_seasons = used is not None and len(_calendar_seasons(parts)) > 1
    policies = list(dict.fromkeys(version.billing_policy for _, version in parts))
    rounding = list(dict.fromkeys(version.rounding_policy for _, version in parts))
    status = weakest_kind(bill.status for bill in bills)
    return PeriodBill(
        period=period,
        consumption_kwh=total_kwh,
        parts=tuple(bills),
        subtotal=Money.sum(bill.subtotal for bill in bills),
        vat=Money.sum(bill.vat for bill in bills),
        total=Money.sum(bill.total for bill in bills),
        status=status,
        split=split,
        billing_policies=tuple(dict.fromkeys(policy.name for policy in policies)),
        billing_policy_status=weakest_kind(policy.status.kind for policy in policies),
        rounding_policies=tuple(dict.fromkeys(policy.name for policy in rounding)),
        rounding_policy_status=weakest_kind(policy.status.kind for policy in rounding),
        warnings=_warnings(bills, policies, split=split, across_seasons=across_seasons),
    )


# ----------------------------------------------------------------------------- versions


def _check_versions(versions: Sequence[TariffVersion]) -> list[TariffVersion]:
    if not versions:
        msg = "at least one tariff version is needed"
        raise IncompatibleVersionsError(msg)
    keys = {(v.supplier, v.tariff_code) for v in versions}
    if len(keys) > 1:
        msg = "the versions must belong to one supplier's tariff"
        raise IncompatibleVersionsError(msg)
    ordered = sorted(versions, key=lambda v: v.effective_from.value)
    for earlier, later in pairwise(ordered):
        end = earlier.effective_to
        if end is None or end.value > later.effective_from.value:
            msg = "tariff versions must not overlap"
            raise IncompatibleVersionsError(msg)
    for version in ordered:
        check_price_basis(version)
    return ordered


# ----------------------------------------------------------------------------- splitting


def _split(
    versions: list[TariffVersion], period: DateRange, vat_table: VatTable
) -> list[tuple[DateRange, TariffVersion]]:
    cuts = {period.start, period.end}
    cuts |= _month_starts(period)
    for version in versions:
        cuts |= {d for d in _version_edges(version) if period.start < d < period.end}
        own = _overlap(version, period)  # a version's seasons cut only its own days
        if own is not None:
            for component in version.components:
                if isinstance(component, SeasonalEnergy):
                    cuts |= _season_starts([s.dates.value for s in component.seasons], own)
            calendar = version.tou_calendar
            if calendar is not None and any(c.needs_calendar for c in version.components):
                cuts |= _season_starts([s.dates.value for s in calendar.seasons], own)
    # The VAT table is contiguous, so every change is some rate's end; a period reaching
    # past the table's first start or last end is refused by `rate_for` either way.
    cuts |= {
        rate.end for rate in vat_table.rates if rate.end and period.start < rate.end < period.end
    }
    ordered = sorted(cuts)
    parts = []
    for start, end in pairwise(ordered):
        part = DateRange(start=start, end=end)
        parts.append((part, _version_for(versions, part)))
    return parts


def _calendar_seasons(parts: list[tuple[DateRange, TariffVersion]]) -> set[str]:
    return {
        version.tou_calendar.season_for(part.start).name
        for part, version in parts
        if version.tou_calendar is not None
    }


def _check_each_season_has_the_periods(
    parts: list[tuple[DateRange, TariffVersion]], used: dict[TouPeriod, Decimal]
) -> None:
    """Sharing by days puts some of each period's kWh in every part, so every part's season
    must have every period with use; otherwise no share-out can be priced."""
    given = {period for period, kwh in used.items() if kwh > 0}
    for part, version in parts:
        calendar = version.tou_calendar
        if calendar is None:  # pragma: no cover - read_consumption refused this version
            continue
        season = calendar.season_for(part.start).name
        missing = sorted(given - calendar.periods_in(season))
        if missing:
            msg = (
                f"kWh for {', '.join(missing)} cannot be shared over this period: the "
                f"{season} season it reaches does not have that period, so a bill per "
                "season, or interval readings, are needed"
            )
            raise UndefinedPeriodError(msg)


def _overlap(version: TariffVersion, period: DateRange) -> DateRange | None:
    end = version.effective_to
    start = max(period.start, version.effective_from.value)
    stop = period.end if end is None else min(period.end, end.value)
    return DateRange(start=start, end=stop) if start < stop else None


def _month_starts(period: DateRange) -> set[date]:
    starts: set[date] = set()
    year, month = period.start.year, period.start.month
    while (year, month) != (date.max.year, 12):  # no month starts after December 9999
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        first = date(year, month, 1)
        if first >= period.end:
            break
        starts.add(first)
    return starts


def _version_edges(version: TariffVersion) -> list[date]:
    end = version.effective_to
    return [version.effective_from.value] + ([] if end is None else [end.value])


def _season_starts(seasons: list[SeasonDates], period: DateRange) -> set[date]:
    starts: set[date] = set()
    for dates in seasons:
        for year in range(period.start.year, period.end.year + 1):
            if (dates.start_month, dates.start_day) == (2, 29) and not calendar.isleap(year):
                start = date(year, 3, 1)  # without 29 February the season starts on 1 March
            else:
                start = date(year, dates.start_month, dates.start_day)
            if period.start < start < period.end:
                starts.add(start)
    return starts


def _version_for(versions: list[TariffVersion], part: DateRange) -> TariffVersion:
    for version in versions:
        if version.covers(part):
            return version
    msg = f"no tariff version covers {part.start.isoformat()} to {part.end.isoformat()}"
    raise PeriodOutsideVersionError(msg)


# ----------------------------------------------------------------------------- sharing


def _factor(numerator: int, denominator: int, point: Quantisation | None) -> Decimal:
    """numerator / denominator, rounded at the pro-rating point, or exact (refused when it
    does not terminate) when the policy names no point."""
    if point is None:
        with exact():
            return Decimal(numerator) / Decimal(denominator)
    return point.divide(Decimal(numerator), Decimal(denominator))


def _shares(
    total: Decimal, period: DateRange, parts: list[DateRange], first: TariffVersion
) -> list[Decimal]:
    """The kWh of each part, by the consumption split of the version covering the period's
    first day (one rounding for the whole share-out)."""
    point = first.rounding_policy.pro_rating
    match first.billing_policy.consumption_split:
        case ConsumptionSplit.BY_DAYS:
            return _shares_by_days(total, period, parts, point)
        case unknown:  # pragma: no cover  # every member is handled above
            assert_never(unknown)


def _shares_by_days(
    total: Decimal, period: DateRange, parts: list[DateRange], point: Quantisation | None
) -> list[Decimal]:
    shares = []
    previous = Decimal(0)
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            cumulative = total
        else:
            days = (part.end - period.start).days
            with exact():
                cumulative = total * _factor(days, period.days, point)
        with exact():
            shares.append(cumulative - previous)
        previous = cumulative
    return shares


def _month_fraction(part: DateRange, version: TariffVersion, *, eligible: bool) -> Decimal | None:
    """The fraction of a month that the part's monthly values are scaled by, or `None`
    for a whole calendar month or a version with no monthly values for this customer."""
    if part.is_whole_calendar_month or not has_monthly_values(version, eligible=eligible):
        return None
    point = version.rounding_policy.pro_rating
    match version.billing_policy.pro_rating:
        case ProRating.BY_DAYS:
            month_days = calendar.monthrange(part.start.year, part.start.month)[1]
            return _factor(part.days, month_days, point)
        case unknown:  # pragma: no cover  # every member is handled above
            assert_never(unknown)


# ----------------------------------------------------------------------------- warnings


def _warnings(
    bills: list[Bill], policies: list[BillingPolicy], *, split: bool, across_seasons: bool
) -> tuple[BillWarning, ...]:
    # One warning per distinct message: parts priced by different versions may warn about
    # different policies or statuses, and none of them may be lost.
    seen: dict[tuple[WarningCode, str], BillWarning] = {}
    for bill in bills:
        for warning in bill.warnings:
            seen.setdefault((warning.code, warning.message), warning)
    unverified = [policy for policy in policies if policy.needs_warning]
    if split and unverified:
        names = ", ".join(f"'{policy.name}'" for policy in unverified)
        warning = BillWarning(
            code=WarningCode.UNVERIFIED_BILLING_POLICY,
            message=(
                f"The period was split (and pro-rated where monthly values apply) by billing "
                f"policy {names}, which is not verified; how the supplier shares a period may "
                "differ."
            ),
        )
        seen[(warning.code, warning.message)] = warning
    if across_seasons:
        warning = BillWarning(
            code=WarningCode.TIME_OF_USE_SHARED_ACROSS_SEASONS,
            message=(
                "The kWh of each time-of-use period were shared between seasons by days; "
                "the supplier bills each season's metered use, so the bill may differ, "
                "even if the billing policy is verified."
            ),
        )
        seen[(warning.code, warning.message)] = warning
    return tuple(seen.values())
