"""Typed tariff components (ADR-0004): declarative data that the engine evaluates.

Each component is a strict, versioned (`schema_version`) model, and every value inside it
is a `Cited` value with its own citation and status (ADR-0006). A component's status is
the weakest status of its values. P1 builds `FixedCharge`, `FlatEnergy` and `BlockEnergy`;
the other types in ADR-0004 arrive with the phase that needs them, each with an ADR.

Block thresholds are kWh per calendar month (how SA tariff schedules print them). How a
threshold applies to a period that is not one calendar month is a policy decided in P1-13;
until then the engine refuses such periods for block tariffs.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import (
    Cited,
    Estimated,
    StatusKind,
    UserProvided,
    Verified,
    weakest,
)
from munisense.domain.money import CanonicalUnit, ExactDecimal, Rate

ComponentName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Status = Verified | Estimated | UserProvided


class VatTreatment(StrEnum):
    """How VAT applies to a component's amount."""

    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"


def _require_unit(rate: Cited[Rate], allowed: set[CanonicalUnit], what: str) -> None:
    if rate.value.canonical_unit not in allowed:
        msg = f"{what} must be priced per {' or per '.join(sorted(u.value for u in allowed))}"
        raise ValueError(msg)
    if rate.value.value < 0:
        msg = f"{what} must not be negative"
        raise ValueError(msg)


class _ComponentBase(DomainModel):
    schema_version: Literal[1] = 1
    name: ComponentName
    vat: Cited[VatTreatment]

    def _statuses(self) -> list[Status]:
        return [self.vat.status]

    @property
    def status(self) -> StatusKind:
        """The weakest status of the component's values (ADR-0004)."""
        return weakest(self._statuses())


class FixedCharge(_ComponentBase):
    """A charge per day or per month, whatever the consumption."""

    kind: Literal["fixed_charge"] = "fixed_charge"
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_day_or_month(self) -> Self:
        allowed = {CanonicalUnit.RAND_PER_DAY, CanonicalUnit.RAND_PER_MONTH}
        _require_unit(self.rate, allowed, "a fixed charge")
        return self

    def _statuses(self) -> list[Status]:
        return [*super()._statuses(), self.rate.status]


class FlatEnergy(_ComponentBase):
    """One energy rate for every kWh."""

    kind: Literal["flat_energy"] = "flat_energy"
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_kwh(self) -> Self:
        _require_unit(self.rate, {CanonicalUnit.RAND_PER_KWH}, "an energy rate")
        return self

    def _statuses(self) -> list[Status]:
        return [*super()._statuses(), self.rate.status]


class Block(DomainModel):
    """One inclining block: its rate applies to kWh above the previous threshold, up to
    `up_to_kwh` (per calendar month). `None` marks the open-ended last block."""

    up_to_kwh: Cited[ExactDecimal] | None
    rate: Cited[Rate]

    @model_validator(mode="after")
    def _per_kwh(self) -> Self:
        _require_unit(self.rate, {CanonicalUnit.RAND_PER_KWH}, "a block rate")
        return self


class BlockEnergy(_ComponentBase):
    """Inclining block energy: ordered blocks, the last one open-ended."""

    kind: Literal["block_energy"] = "block_energy"
    blocks: Annotated[tuple[Block, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def _ordered_with_open_last_block(self) -> Self:
        *bounded, last = self.blocks
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
        return self

    def bounds(self) -> list[tuple[Decimal, Decimal | None]]:
        """Each block's (from, up to) kWh; the last block's upper bound is `None`."""
        result: list[tuple[Decimal, Decimal | None]] = []
        lower = Decimal(0)
        for item in self.blocks:
            upper = None if item.up_to_kwh is None else item.up_to_kwh.value
            result.append((lower, upper))
            if upper is not None:
                lower = upper
        return result

    def _statuses(self) -> list[Status]:
        statuses = [*super()._statuses()]
        for item in self.blocks:
            statuses.append(item.rate.status)
            if item.up_to_kwh is not None:
                statuses.append(item.up_to_kwh.status)
        return statuses


Component = Annotated[FixedCharge | FlatEnergy | BlockEnergy, Field(discriminator="kind")]
