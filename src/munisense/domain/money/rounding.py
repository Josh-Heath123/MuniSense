"""Rounding policies: the only place where amounts and kWh are quantised (ADR-0005).

A `RoundingPolicy` names each quantisation point a supplier uses. A point set to `None` is
not quantised. Policies are data, chosen per tariff version; no rule is hard-coded. A
policy not yet confirmed from real bills is `estimated`, and every result that uses it
carries a warning.
"""

import decimal
from decimal import Context, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Self

from pydantic import StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import StatusKind, VerificationStatus
from munisense.domain.money.exact import EXACT_PRECISION, ExactDecimal


class RoundingMode(StrEnum):
    """How a value is rounded to its step (Python decimal rounding modes)."""

    HALF_UP = "half_up"
    HALF_EVEN = "half_even"
    DOWN = "down"
    UP = "up"
    FLOOR = "floor"
    CEILING = "ceiling"


_DECIMAL_MODES = {
    RoundingMode.HALF_UP: decimal.ROUND_HALF_UP,
    RoundingMode.HALF_EVEN: decimal.ROUND_HALF_EVEN,
    RoundingMode.DOWN: decimal.ROUND_DOWN,
    RoundingMode.UP: decimal.ROUND_UP,
    RoundingMode.FLOOR: decimal.ROUND_FLOOR,
    RoundingMode.CEILING: decimal.ROUND_CEILING,
}


class Quantisation(DomainModel):
    """Round to a power-of-ten step (1, 0.1, 0.01, ...) with a named mode."""

    step: ExactDecimal
    mode: RoundingMode

    @model_validator(mode="after")
    def _power_of_ten_at_most_one(self) -> Self:
        sign, digits, exponent = self.step.normalize().as_tuple()
        if sign or digits != (1,) or not isinstance(exponent, int) or exponent > 0:
            msg = "a rounding step must be 1, 0.1, 0.01 or a smaller power of ten"
            raise ValueError(msg)
        return self

    def apply(self, value: Decimal) -> Decimal:
        """Round `value` to the step. This is deliberate rounding, so it is allowed here."""
        context = Context(prec=EXACT_PRECISION, traps=[InvalidOperation])
        return value.quantize(
            self.step.normalize(), rounding=_DECIMAL_MODES[self.mode], context=context
        )


class VatApplication(StrEnum):
    """Where VAT is calculated."""

    PER_LINE = "per_line"
    ON_SUBTOTAL = "on_subtotal"


class RoundingPolicy(DomainModel):
    """A supplier's named quantisation points (ADR-0005), with its own status.

    A rounding policy is learnt from bills rather than printed in a tariff document, so it
    carries a status but no citation; an `estimated` policy says why in its reason.
    """

    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    line_amount: Quantisation | None
    vat_application: VatApplication
    vat_amount: Quantisation | None
    total: Quantisation | None
    prepaid_kwh: Quantisation | None
    status: VerificationStatus

    @property
    def is_estimated(self) -> bool:
        return self.status.kind is not StatusKind.VERIFIED
