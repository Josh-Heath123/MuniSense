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
from munisense.domain.tariffs.components import Component, PrintedLabel

Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


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
        return self

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
