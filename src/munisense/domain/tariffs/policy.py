"""Billing policies: how a supplier applies its tariff to a period (E38, ADR-0011).

A billing policy is learnt from bills, like a rounding policy, not printed as a value in a
schedule, so it carries its own status and evidence. It names how a period is split and
shared (P1-13) and how prepaid purchases are applied (P1-14): when blocks reset, and how
monthly fixed charges are recovered from a prepaid customer.
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


class BlockReset(StrEnum):
    """Which earlier purchases count towards the blocks of a prepaid purchase."""

    CALENDAR_MONTH = "calendar_month"
    """kWh bought since the start of the purchase's calendar month count; blocks start
    again on the first day of each month."""


class PrepaidFixedCharges(StrEnum):
    """How a prepaid customer pays the tariff's monthly fixed charges and levies."""

    FIRST_PURCHASE_OF_MONTH = "first_purchase_of_month"
    """Deducted, with VAT, from the first purchase of each calendar month."""
    NOT_FROM_PURCHASES = "not_from_purchases"
    """Not deducted from purchases (for example billed separately); purchases buy energy."""


class ExportCap(StrEnum):
    """How much exported energy an export credit pays for (ADR-0016 point 6)."""

    USE_IN_PERIOD_PER_CALENDAR_MONTH = "use_in_period_per_calendar_month"
    """In each time-of-use period, at most the kWh used in that period in the same calendar
    month (Eskom: "up to and equal to the consumption per time-of-use period", credited "at
    the end of each month"; reading "month" as the calendar month is this policy's choice)."""


class BillingPolicy(DomainModel):
    """A supplier's named way of applying its tariff to a billing period."""

    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    pro_rating: ProRating
    consumption_split: ConsumptionSplit
    block_reset: BlockReset
    prepaid_fixed_charges: PrepaidFixedCharges
    export_cap: ExportCap | None = Field(default=None, exclude_if=lambda value: value is None)
    """Needed by a version with an export credit (P4-8); added under schema version 1 and
    left out of the output when absent (ADR-0016 point 3)."""
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
