"""A tariff version: a header plus an ordered list of typed components (ADR-0004).

The header's values are cited like every other value: the tariff's printed name, the
printed statement of whom it applies to (for example "Domestic, prepaid, single phase"),
the effective dates and the price basis. `supplier`, `tariff_code` and `customer_class`
are catalogue keys chosen by us, not values printed in the schedule, so they are not
cited; the printed name and applicability are the cited facts behind them. Variants of a
tariff (prepaid and credit, single and three phase) are separate versions with separate
tariff codes until a component needs an applicability condition (an ADR). The
rounding policy is part of the version, because it is supplier behaviour that can change
from one year to the next. Record time (when we learnt of a version) is added by the
publish step in P2; here a version carries only its valid time.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Cited, StatusKind, cited_statuses, weakest
from munisense.domain.money import RoundingPolicy
from munisense.domain.periods import DateRange
from munisense.domain.tariffs.components import (
    BlockEnergy,
    Component,
    FlatEnergy,
    FreeBasicAllocation,
    PrintedLabel,
    SeasonalEnergy,
    SeasonDates,
    TimeOfUseEnergy,
)
from munisense.domain.tariffs.policy import BillingPolicy
from munisense.domain.tariffs.time_of_use import TouCalendar

Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
MAX_HOLIDAY_COVERAGE_DAYS = 731  # two years, a leap day included


class PriceBasis(StrEnum):
    """Whether the schedule prints prices with or without VAT."""

    EXCLUDING_VAT = "excluding_vat"
    INCLUDING_VAT = "including_vat"


class TariffVersion(DomainModel):
    """One version of one supplier's tariff, valid from `effective_from` (inclusive) to
    `effective_to` (exclusive; `None` while no later version is known)."""

    schema_version: Literal[1]
    supplier: Code
    tariff_code: Code
    customer_class: Code
    printed_name: Cited[PrintedLabel]
    applies_to: Cited[PrintedLabel]
    effective_from: Cited[date]
    effective_to: Cited[date] | None
    price_basis: Cited[PriceBasis]
    rounding_policy: RoundingPolicy
    billing_policy: BillingPolicy
    tou_calendar: TouCalendar | None = Field(default=None, exclude_if=lambda value: value is None)
    """The version's time-of-use calendar (ADR-0016). Added under schema version 1 and left
    out of the output when absent, so files without one stay byte-identical (ADR-0016
    point 3)."""
    components: Annotated[tuple[Component, ...], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.effective_to is not None and self.effective_to.value <= self.effective_from.value:
            msg = "a tariff version must end after it starts"
            raise ValueError(msg)
        names = [component.name for component in self.components]
        if len(set(names)) != len(names):
            msg = "component names must be unique within a version"
            raise ValueError(msg)
        self._check_free_basic_allocation()
        self._check_calendar()
        return self

    def _check_calendar(self) -> None:
        """A time-of-use component needs the calendar; a holiday list must cover the
        version's dates; every seasonal component must agree, season by season, with the
        calendar or, without one, with the other seasonal components (TD-11, ADR-0016
        point 2)."""
        calendar = self.tou_calendar
        if calendar is None:
            needing = [c.name for c in self.components if c.needs_calendar]
            if needing:
                msg = f"the component(s) {', '.join(needing)} need a time-of-use calendar"
                raise ValueError(msg)
        else:
            self._check_holiday_coverage(calendar)
            self._check_time_of_use_rates(calendar)
        seasons: dict[str, SeasonDates] = (
            {s.name: s.dates.value for s in calendar.seasons} if calendar is not None else {}
        )
        calendar_names = {s.name for s in calendar.seasons} if calendar is not None else set()
        for component in self.components:
            if not isinstance(component, SeasonalEnergy):
                continue
            for season in component.seasons:
                known = seasons.setdefault(season.name, season.dates.value)
                if calendar is not None and season.name not in calendar_names:
                    msg = (
                        f"the season {season.name!r} of {component.name} is not in the "
                        "version's calendar"
                    )
                    raise ValueError(msg)
                if season.dates.value != known:
                    against = "the calendar's" if calendar is not None else "another component's"
                    msg = (
                        f"the season {season.name!r} of {component.name} has dates that differ "
                        f"from {against}"
                    )
                    raise ValueError(msg)

    def _check_time_of_use_rates(self, calendar: TouCalendar) -> None:
        """Each time-of-use energy charge has a rate for exactly the periods each season
        of the calendar uses: none missing, none for a season or period it lacks (P4-7)."""
        expected = {(s.name, p) for s in calendar.seasons for p in calendar.periods_in(s.name)}
        for component in self.components:
            if not isinstance(component, TimeOfUseEnergy):
                continue
            given = {(r.season, r.period) for r in component.rates}
            if given - expected:
                season, period = min(given - expected)
                msg = (
                    f"{component.name} has a rate for {period} in the season {season!r}, "
                    "which the calendar does not define there"
                )
                raise ValueError(msg)
            if expected - given:
                season, period = min(expected - given)
                msg = f"{component.name} has no rate for {period} in the season {season!r}"
                raise ValueError(msg)

    def _check_holiday_coverage(self, calendar: TouCalendar) -> None:
        """A holiday list must cover every day of the version, and at most two years, so a
        mistyped end cannot price later holidays as ordinary days (P4-6 security review)."""
        coverage = calendar.holidays.coverage
        if coverage is None:
            return
        window = coverage.value
        if window.days > MAX_HOLIDAY_COVERAGE_DAYS:
            msg = f"a holiday list covers at most {MAX_HOLIDAY_COVERAGE_DAYS} days"
            raise ValueError(msg)
        if self.effective_to is None:
            # No finite list covers an open-ended version, and a mistyped end within the
            # cap would price later holidays as ordinary days (P4-6 security review).
            msg = "a version with a holiday list needs its end date"
            raise ValueError(msg)
        if not window.contains(self.effective_from.value) or window.end < self.effective_to.value:
            msg = "the holiday list must cover every day of the version"
            raise ValueError(msg)

    def _check_free_basic_allocation(self) -> None:
        allocations = [c for c in self.components if isinstance(c, FreeBasicAllocation)]
        if len(allocations) > 1:
            msg = "a tariff version has at most one free basic allocation"
            raise ValueError(msg)
        energy = {
            c.name: c
            for c in self.components
            if isinstance(c, FlatEnergy | BlockEnergy | SeasonalEnergy)
        }
        for allocation in allocations:
            target = energy.get(allocation.energy_component)
            if target is None:
                msg = (
                    "a free basic allocation must name an energy component (flat, block or "
                    "seasonal) of the same version"
                )
                raise ValueError(msg)
            # The credit removes the energy's own charge, so it must be taxed the same way;
            # otherwise a zero-rated charge and its standard-rated credit leave negative VAT.
            if allocation.vat.value is not target.vat.value:
                msg = "a free basic allocation must have the VAT treatment of its energy"
                raise ValueError(msg)

    @property
    def free_basic_allocation(self) -> FreeBasicAllocation | None:
        """The version's free basic allocation, if it offers one."""
        for component in self.components:
            if isinstance(component, FreeBasicAllocation):
                return component
        return None

    def covers(self, period: DateRange) -> bool:
        """True when the whole period falls inside the version's effective range."""
        end = None if self.effective_to is None else self.effective_to.value
        return self.effective_from.value <= period.start and (end is None or period.end <= end)

    @property
    def status(self) -> StatusKind:
        """The weakest status of every cited value in the header and the components.

        The rounding policy holds no cited values; its own status is reported separately
        on each result (ADR-0005).
        """
        return weakest(cited_statuses(self))
