"""Typed tariff components (ADR-0004): declarative data that the engine evaluates.

Each component is a strict, versioned (`schema_version`, required) model, and every value
inside it is a `Cited` value with its own citation and status (ADR-0006), including the
label printed in the schedule. A component's status is the weakest status of all its
cited values, found by walking its fields (`cited_statuses`), so no value can be left out.

P1 builds `FixedCharge`, `FlatEnergy`, `BlockEnergy`, `Levy` and `FreeBasicAllocation`
(all listed in ADR-0004); the other types listed there arrive with the phase that needs
them. A type not listed in ADR-0004 needs a new ADR.

Block thresholds are kWh per calendar month (how SA tariff schedules print them). How a
threshold applies to a period that is not one calendar month is a policy decided in P1-13;
until then the engine refuses such periods for block tariffs (P1-7 criterion).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Cited, StatusKind, cited_statuses, weakest
from munisense.domain.money import CanonicalUnit, ExactDecimal, Rate

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


class BlockEnergy(_ComponentBase):
    """Block energy: ordered blocks, the last one open-ended. Rates usually rise (inclining
    blocks) but are not required to."""

    kind: Literal["block_energy"]
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
    """The name of the `FlatEnergy` or `BlockEnergy` component whose kWh are free."""

    @model_validator(mode="after")
    def _positive(self) -> Self:
        if self.free_kwh.value <= 0:
            msg = "a free basic allocation must be a positive number of kWh"
            raise ValueError(msg)
        return self


Component = Annotated[
    FixedCharge | FlatEnergy | BlockEnergy | Levy | FreeBasicAllocation,
    Field(discriminator="kind"),
]
