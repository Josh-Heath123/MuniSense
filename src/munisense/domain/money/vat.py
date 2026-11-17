"""The dated VAT rate table (ADR-0005: the VAT rate comes from data, never a constant).

Each entry runs from `start` up to, but not including, `end`; the last entry may be open
(`end` is `None`, "until changed"). Entries are ordered, contiguous and never overlap. A
period with no rate, or one that straddles a rate change, is refused; splitting a period
at a change is P1-13's job.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Cited
from munisense.domain.money.errors import NoVatRateError, VatRateChangesError
from munisense.domain.money.exact import ExactDecimal, exact
from munisense.domain.periods import DateRange


class VatRate(DomainModel):
    """One VAT rate valid from `start` until `end` (exclusive). Each value is cited.

    The effective dates are tariff data like the percentage (CLAUDE.md rule 1), so each
    carries its own citation and status. `end` is `None` while no later rate is known.
    """

    start_cited: Cited[date]
    end_cited: Cited[date] | None
    percent: Cited[ExactDecimal]

    @property
    def start(self) -> date:
        return self.start_cited.value

    @property
    def end(self) -> date | None:
        return None if self.end_cited is None else self.end_cited.value

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.end is not None and self.end <= self.start:
            msg = "a VAT rate must end after it starts"
            raise ValueError(msg)
        if not Decimal(0) <= self.percent.value <= Decimal(100):
            msg = "a VAT percentage must be between 0 and 100"
            raise ValueError(msg)
        return self

    @property
    def fraction(self) -> Decimal:
        """The rate as a fraction (15 percent is 0.15), shifted exactly."""
        with exact():
            return self.percent.value.scaleb(-2)

    def covers(self, period: DateRange) -> bool:
        return self.start <= period.start and (self.end is None or period.end <= self.end)

    def touches(self, period: DateRange) -> bool:
        return self.start < period.end and (self.end is None or period.start < self.end)


class VatTable(DomainModel):
    """Contiguous, ordered VAT rates."""

    rates: Annotated[tuple[VatRate, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _contiguous(self) -> Self:
        for earlier, later in zip(self.rates, self.rates[1:], strict=False):
            if earlier.end != later.start:
                msg = "VAT rates must be in date order, without gaps or overlaps"
                raise ValueError(msg)
        return self

    def rate_for(self, period: DateRange) -> VatRate:
        """The single rate that covers the whole period; refuses otherwise."""
        touching = [rate for rate in self.rates if rate.touches(period)]
        if len(touching) == 1 and touching[0].covers(period):
            return touching[0]
        if len(touching) > 1:
            msg = "the VAT rate changes inside this period; it must be split first"
            raise VatRateChangesError(msg)
        msg = "no VAT rate is recorded for the whole of this period"
        raise NoVatRateError(msg)
