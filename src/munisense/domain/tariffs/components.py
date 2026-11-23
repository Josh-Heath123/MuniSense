"""Typed tariff components (ADR-0004): declarative data that the engine evaluates.

Each component is a strict, versioned (`schema_version`, required) model, and every value
inside it is a `Cited` value with its own citation and status (ADR-0006), including the
label printed in the schedule. A component's status is the weakest status of all its
cited values, found by walking its fields (`cited_statuses`), so no value can be left out.

P1 builds `FixedCharge`, `FlatEnergy`, `BlockEnergy`, `SeasonalEnergy`, `Levy` and
`FreeBasicAllocation` (all listed in ADR-0004); the other types listed there arrive with
the phase that needs them. A type not listed in ADR-0004 needs a new ADR.

Block thresholds are kWh per calendar month (how SA tariff schedules print them). How a
threshold applies to a period that is not one calendar month is a policy decided in P1-13;
until then the engine refuses such periods for block tariffs (P1-7 criterion).
"""

from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Cited, StatusKind, cited_statuses, weakest
from munisense.domain.money import CanonicalUnit, ExactDecimal, Rate
from munisense.domain.tariffs.tou_period import TouPeriod

ComponentName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
PrintedLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$"
    ),
]
"""A label as printed in the schedule, for example "Basic charge" or "Tariff A: Domestic"."""


class VatTreatment(StrEnum):
    """How VAT applies to a component's amount."""

    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"


def _require_unit(rate: Cited[Rate], allowed: set[CanonicalUnit], what: str) -> None:
    if rate.value.canonical_unit not in allowed:
        msg = f"{what} must be priced per {' or per '.join(sorted(u.value for u in allowed))}"
        raise ValueError(msg)
    if rate.value.value.is_signed():
        msg = f"{what} must not be negative (nor negative zero)"
        raise ValueError(msg)


class _ComponentBase(DomainModel):
    schema_version: Literal[1]
    name: ComponentName
    label: Cited[PrintedLabel]
    vat: Cited[VatTreatment]

    @property
    def status(self) -> StatusKind:
        """The weakest status of all the component's cited values (ADR-0004)."""
        return weakest(cited_statuses(self))

    @property
    def needs_calendar(self) -> bool:
        """True when this component is priced by time of use, so its version must carry a
        calendar (ADR-0016 point 1). Per instance: a charge limited to seasons or periods
        needs one, the same charge unlimited does not (P4-9)."""
        return False


class FixedCharge(_ComponentBase):
    """A charge per day or per month, whatever the consumption."""

    kind: Literal["fixed_charge"]
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_day_or_month(self) -> Self:
        allowed = {CanonicalUnit.RAND_PER_DAY, CanonicalUnit.RAND_PER_MONTH}
        _require_unit(self.rate, allowed, "a fixed charge")
        return self


class FlatEnergy(_ComponentBase):
    """One energy rate for every kWh."""

    kind: Literal["flat_energy"]
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_kwh(self) -> Self:
        _require_unit(self.rate, {CanonicalUnit.RAND_PER_KWH}, "an energy rate")
        return self


class Block(DomainModel):
    """One block: its rate applies to kWh above the previous threshold, up to `up_to_kwh`
    (per calendar month). `None` marks the open-ended last block.

    kWh are continuous, so a schedule printing "0-50 / 51-350 / >350" means blocks up to
    50 and up to 350; the printed text is kept in the citation.
    """

    up_to_kwh: Cited[ExactDecimal] | None
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_kwh(self) -> Self:
        _require_unit(self.rate, {CanonicalUnit.RAND_PER_KWH}, "a block rate")
        return self


def _check_blocks(blocks: tuple[Block, ...]) -> None:
    *bounded, last = blocks
    if last.up_to_kwh is not None:
        msg = "the last block must be open-ended"
        raise ValueError(msg)
    previous = Decimal(0)
    for item in bounded:
        if item.up_to_kwh is None:
            msg = "only the last block may be open-ended"
            raise ValueError(msg)
        if item.up_to_kwh.value <= previous:
            msg = "block thresholds must be positive and strictly increasing"
            raise ValueError(msg)
        previous = item.up_to_kwh.value


class BlockEnergy(_ComponentBase):
    """Block energy: ordered blocks, the last one open-ended. Rates usually rise (inclining
    blocks) but are not required to."""

    kind: Literal["block_energy"]
    blocks: Annotated[tuple[Block, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def _ordered_with_open_last_block(self) -> Self:
        _check_blocks(self.blocks)
        return self

    def bounds(self) -> list[tuple[Decimal, Decimal | None]]:
        """Each block's (from, up to) kWh; the last block's upper bound is `None`.

        Gaps cannot occur: only upper bounds are stored, and each block starts where the
        previous one ends.
        """
        result: list[tuple[Decimal, Decimal | None]] = []
        lower = Decimal(0)
        for item in self.blocks:
            upper = None if item.up_to_kwh is None else item.up_to_kwh.value
            result.append((lower, upper))
            if upper is not None:
                lower = upper
        return result


_LEAP_YEAR = 2028  # a calendar year with 29 February, used to check that seasons cover every day
Month = Annotated[int, Field(ge=1, le=12)]
Day = Annotated[int, Field(ge=1, le=31)]


class SeasonDates(DomainModel):
    """The days a season covers each year, from the start day to the end day, both
    inclusive (as schedules print them: "June, July, and August" is 1 June to 31 August).
    A season may wrap past the new year ("September to May" is 1 September to 31 May)."""

    start_month: Month
    start_day: Day
    end_month: Month
    end_day: Day

    @model_validator(mode="after")
    def _real_days(self) -> Self:
        for month, day in ((self.start_month, self.start_day), (self.end_month, self.end_day)):
            try:
                date(_LEAP_YEAR, month, day)
            except ValueError:
                msg = f"{month:02d}-{day:02d} is not a day of the year"
                raise ValueError(msg) from None
        return self

    def contains(self, day: date) -> bool:
        """True when `day` falls in this season (in any year)."""
        key = (day.month, day.day)
        start = (self.start_month, self.start_day)
        end = (self.end_month, self.end_day)
        if start <= end:
            return start <= key <= end
        return key >= start or key <= end  # wraps past the new year


def check_covers_the_year_once(seasons: list[SeasonDates]) -> None:
    """Refuse seasons that leave a day of the year (a leap year, so 29 February counts)
    uncovered, or cover one twice. Shared by seasonal components and the TOU calendar."""
    day = date(_LEAP_YEAR, 1, 1)
    while day.year == _LEAP_YEAR:
        covering = sum(dates.contains(day) for dates in seasons)
        if covering != 1:
            problem = "no season" if covering == 0 else "more than one season"
            msg = f"the seasons must cover every day once; {day:%d %B} has {problem}"
            raise ValueError(msg)
        day += timedelta(days=1)


class Season(DomainModel):
    """One season of a seasonal energy charge: its cited dates and its own cited rates.
    A flat rate is a single open-ended block."""

    name: ComponentName
    label: Cited[PrintedLabel]
    dates: Cited[SeasonDates]
    blocks: Annotated[tuple[Block, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def _ordered_with_open_last_block(self) -> Self:
        _check_blocks(self.blocks)
        return self


class SeasonalEnergy(_ComponentBase):
    """Energy priced by season. The seasons (a calendar in data) must cover every day of
    the year exactly once; a gap or an overlap is refused. A billing period is priced with
    the one season that contains all of it; a period across a season boundary is refused
    until period splitting exists (P1-13)."""

    kind: Literal["seasonal_energy"]
    seasons: Annotated[tuple[Season, ...], Field(min_length=1, max_length=12)]

    @model_validator(mode="after")
    def _a_calendar_covering_the_year_once(self) -> Self:
        names = [season.name for season in self.seasons]
        if len(set(names)) != len(names):
            msg = "season names must be unique within a component"
            raise ValueError(msg)
        check_covers_the_year_once([season.dates.value for season in self.seasons])
        return self

    def season_for(self, first: date, last: date) -> Season | None:
        """The season containing every day from `first` to `last` (inclusive), or `None`
        when the days cross a season boundary. A season lasts at most a year, so a span of
        more than 366 days always crosses (unless one season covers the whole year);
        otherwise at most 366 days are checked."""
        if len(self.seasons) == 1:
            return self.seasons[0]  # it covers every day (checked when built)
        if (last - first).days >= 366:  # days in the longest year
            return None
        for season in self.seasons:
            if all(
                season.dates.value.contains(first + timedelta(days=offset))
                for offset in range((last - first).days + 1)
            ):
                return season
        return None

    @property
    def has_thresholds(self) -> bool:
        """True when any season has block thresholds (which are per calendar month)."""
        return any(len(season.blocks) > 1 for season in self.seasons)


class Levy(_ComponentBase):
    """A levy imposed by a higher authority (for example an electricity levy that a
    schedule says is "in addition to" its tariffs), charged per kWh, per day or per month.
    It is priced and taxed like any other component; it is a separate type so that a bill
    shows it as a levy and a schedule's levies can be told apart from its own charges."""

    kind: Literal["levy"]
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _priced(self) -> Self:
        allowed = {
            CanonicalUnit.RAND_PER_KWH,
            CanonicalUnit.RAND_PER_DAY,
            CanonicalUnit.RAND_PER_MONTH,
        }
        _require_unit(self.rate, allowed, "a levy")
        return self


class FreeBasicAllocation(_ComponentBase):
    """Free kWh per calendar month for an eligible customer (for example Free Basic
    Electricity), taken from the bottom of one energy component of the same version.

    Eligibility is an input to the calculation, never inferred from the tariff or the
    consumption. The first `free_kwh` kWh of the month cost nothing: the engine credits
    them at the energy component's own rates, block by block, so the credit mirrors the
    charge exactly. Whether a supplier instead shifts the blocks up is a billing policy
    question; only the "first kWh are free" reading is built.
    """

    kind: Literal["free_basic_allocation"]
    free_kwh: Cited[ExactDecimal]
    energy_component: ComponentName
    """The name of the flat, block or seasonal energy component whose kWh are free."""

    @model_validator(mode="after")
    def _positive(self) -> Self:
        if self.free_kwh.value <= 0:
            msg = "a free basic allocation must be a positive number of kWh"
            raise ValueError(msg)
        return self


class TouRate(DomainModel):
    """The rate of one period in one season of a time-of-use energy charge."""

    season: ComponentName
    period: TouPeriod
    rate: Cited[Rate]


class TimeOfUseEnergy(_ComponentBase):
    """Energy priced by time of use (ADR-0016 point 6): a cited rate per kWh for each
    period of each season of the version's calendar. The version checks that the rates
    name exactly the seasons and periods its calendar defines."""

    kind: Literal["time_of_use_energy"]
    rates: Annotated[tuple[TouRate, ...], Field(min_length=1, max_length=36)]

    @model_validator(mode="after")
    def _one_rate_per_season_and_period(self) -> Self:
        keys = [(r.season, r.period) for r in self.rates]
        if len(set(keys)) != len(keys):
            msg = "a time-of-use energy charge has one rate per season and period"
            raise ValueError(msg)
        for rate in self.rates:
            _require_unit(rate.rate, {CanonicalUnit.RAND_PER_KWH}, "a time-of-use energy rate")
        return self

    @property
    def needs_calendar(self) -> bool:
        return True

    def rate_for(self, season: str, period: TouPeriod) -> Cited[Rate]:
        """The rate of a period in a season (the version guarantees there is one)."""
        found = next((r.rate for r in self.rates if (r.season, r.period) == (season, period)), None)
        if found is None:  # pragma: no cover - only reachable if validation was skipped
            msg = f"{self.name} has no rate for {period} in the season {season!r}"
            raise AssertionError(msg)
        return found


Component = Annotated[
    FixedCharge
    | FlatEnergy
    | BlockEnergy
    | SeasonalEnergy
    | TimeOfUseEnergy
    | Levy
    | FreeBasicAllocation,
    Field(discriminator="kind"),
]
