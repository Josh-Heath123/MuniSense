"""Rounding policies: the only place where amounts and kWh are quantised (ADR-0005).

A `RoundingPolicy` names each quantisation point a supplier uses. A point set to `None` is
not quantised. Policies are data, chosen per tariff version; no rule is hard-coded. A
policy not yet confirmed from real bills is `estimated`, and every result that uses it
carries a warning.

`Quantisation.apply` and `Quantisation.divide` are the only operations in the domain that
may round (`test_domain_purity.py` refuses `.quantize` anywhere else). `divide` exists for
results that cannot terminate, such as removing VAT from a VAT-inclusive amount or turning
rand into kWh for a prepaid purchase.
"""

import decimal
import math
from collections.abc import Callable
from decimal import Context, Decimal, DecimalException, InvalidOperation
from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Citation, StatusKind, VerificationStatus
from munisense.domain.money.errors import InvalidArithmeticError
from munisense.domain.money.exact import EXACT_PRECISION, MAX_DECIMAL_PLACES, ExactDecimal


class RoundingMode(StrEnum):
    """How a value is rounded to its step (Python decimal rounding modes).

    For money (`Money.quantised`) the mode applies to the magnitude, so a negative amount
    is rounded as its positive counterpart and negated; `Quantisation.apply` itself rounds
    the signed value."""

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
    """Round to a power-of-ten step (1, 0.1, ... down to 1E-12) with a named mode."""

    step: ExactDecimal
    mode: RoundingMode

    @model_validator(mode="after")
    def _power_of_ten_between_one_and_the_finest_input(self) -> Self:
        sign, digits, exponent = self.step.normalize().as_tuple()
        valid = (
            not sign
            and digits == (1,)
            and isinstance(exponent, int)
            and -MAX_DECIMAL_PLACES <= exponent <= 0
        )
        if not valid:
            msg = "a rounding step must be a power of ten from 1 down to 1E-12"
            raise ValueError(msg)
        return self

    def apply(self, value: Decimal) -> Decimal:
        """Round `value` to the step. Negative zero becomes zero."""
        context = Context(
            prec=EXACT_PRECISION, rounding=_DECIMAL_MODES[self.mode], traps=[InvalidOperation]
        )
        try:
            result = value.quantize(self.step.normalize(), context=context)
        except DecimalException as error:
            msg = "the value cannot be rounded to this step"
            raise InvalidArithmeticError(msg) from error
        return _without_negative_zero(result)

    def divide(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        """`numerator / denominator`, rounded once to the step with this mode, exactly.

        The quotient is kept as an exact fraction, so the rounding decision never depends
        on how many digits were computed.
        """
        if denominator.is_zero():
            msg = "cannot divide by zero"
            raise InvalidArithmeticError(msg)
        if not (numerator.is_finite() and denominator.is_finite()):
            msg = "cannot divide a non-finite number"
            raise InvalidArithmeticError(msg)
        exponent = self.step.normalize().as_tuple().exponent
        assert isinstance(exponent, int)  # noqa: S101 - guaranteed by the validator
        steps = Fraction(numerator) / Fraction(denominator) / Fraction(10) ** exponent
        result = Decimal(_ROUND_FRACTION[self.mode](steps)).scaleb(exponent)
        return _without_negative_zero(result)


def _without_negative_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


def _half_up(value: Fraction) -> int:
    magnitude = math.floor(abs(value) + Fraction(1, 2))
    return magnitude if value >= 0 else -magnitude


def _away_from_zero(value: Fraction) -> int:
    return math.ceil(value) if value >= 0 else math.floor(value)


_ROUND_FRACTION: dict[RoundingMode, Callable[[Fraction], int]] = {
    RoundingMode.HALF_UP: _half_up,
    RoundingMode.HALF_EVEN: round,  # Fraction rounds half to even
    RoundingMode.DOWN: math.trunc,
    RoundingMode.UP: _away_from_zero,
    RoundingMode.FLOOR: math.floor,
    RoundingMode.CEILING: math.ceil,
}


class VatApplication(StrEnum):
    """Where VAT is calculated."""

    PER_LINE = "per_line"
    """On each line's amount, after the line is quantised (if `line_amount` is set)."""
    ON_SUBTOTAL = "on_subtotal"
    """Once, on the sum of the VAT-able lines (after line quantisation, if any)."""


class RoundingPolicy(DomainModel):
    """A supplier's named quantisation points (ADR-0005, ADR-0011), with its own status and
    evidence.

    A rounding policy is learnt from bills rather than printed in a tariff schedule. Its
    evidence is a list of citations of the (anonymised) bills or receipts it was derived
    from. A `verified` or `user_provided` policy must cite at least one; an `estimated`
    policy may have none, and its reason says why (W7, decided by E37).
    """

    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    line_amount: Quantisation | None
    vat_application: VatApplication
    vat_amount: Quantisation | None
    total: Quantisation | None
    pro_rating: Quantisation | None
    """Rounds the apportioning factors when a period is split (ADR-0011): days in a part /
    days in its month for monthly values, and cumulative days / period days for kWh.
    `None` refuses a split whose factors do not terminate."""
    prepaid_kwh: Quantisation | None
    status: VerificationStatus
    evidence: Annotated[tuple[Citation, ...], Field(max_length=100)]

    @model_validator(mode="after")
    def _claims_need_evidence(self) -> Self:
        if self.status.kind is not StatusKind.ESTIMATED and not self.evidence:
            msg = "a verified or user-provided rounding policy must cite its evidence"
            raise ValueError(msg)
        return self

    @property
    def needs_warning(self) -> bool:
        """True unless the policy is verified: results using it must say so."""
        return self.status.kind is not StatusKind.VERIFIED
