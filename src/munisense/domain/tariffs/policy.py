"""Billing policies: how a supplier applies its tariff to a period (E38, ADR-0011).

A billing policy is learnt from bills, like a rounding policy, not printed as a value in a
schedule, so it carries its own status and evidence. P1-13 builds how a period is split
and shared; prepaid policies (block reset, how fixed charges are recovered) arrive in
P1-14.
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Citation, StatusKind, VerificationStatus


class ProRating(StrEnum):
    """How a monthly value (a basic charge, a monthly levy, a block threshold, a free
    monthly allocation) applies to part of a calendar month."""

    BY_DAYS = "by_days"
    """Multiplied by the days in the part / the days in that calendar month."""


class ConsumptionSplit(StrEnum):
    """How the kWh of a period are shared among its parts when the period is split."""

    BY_DAYS = "by_days"
    """In proportion to days, as if the kWh were used evenly over the period."""


class BillingPolicy(DomainModel):
    """A supplier's named way of applying its tariff to a billing period."""

    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    pro_rating: ProRating
    consumption_split: ConsumptionSplit
    status: VerificationStatus
    evidence: Annotated[tuple[Citation, ...], Field(max_length=100)]
    """Citations of what the policy rests on: a schedule's own words (for example "billed
    pro rata") or anonymised bills that show the method."""

    @model_validator(mode="after")
    def _claims_need_evidence(self) -> Self:
        if self.status.kind is not StatusKind.ESTIMATED and not self.evidence:
            msg = "a verified or user-provided billing policy must cite its evidence"
            raise ValueError(msg)
        return self

    @property
    def needs_warning(self) -> bool:
        """True unless the policy is verified: results that use it must say so."""
        return self.status.kind is not StatusKind.VERIFIED
