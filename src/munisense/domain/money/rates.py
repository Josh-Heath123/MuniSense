"""Rates as printed in a tariff document, with an exact canonical form (ADR-0005).

A `Rate` keeps the value and unit exactly as printed (for example 234.6700 c/kWh). Its
canonical form is in rand per unit of quantity (R/kWh, R/day or R/month), converted
without rounding.
"""

from decimal import Decimal
from enum import StrEnum

from munisense.domain.base import DomainModel
from munisense.domain.money.amount import Money
from munisense.domain.money.exact import ExactDecimal, exact


class RateUnit(StrEnum):
    """Units in which tariff documents print rates."""

    CENTS_PER_KWH = "c/kWh"
    RAND_PER_KWH = "R/kWh"
    RAND_PER_DAY = "R/day"
    RAND_PER_MONTH = "R/month"


class CanonicalUnit(StrEnum):
    """What a rate is charged per, in rand."""

    RAND_PER_KWH = "R/kWh"
    RAND_PER_DAY = "R/day"
    RAND_PER_MONTH = "R/month"


# (cents-to-rand exponent shift, canonical unit) per printed unit.
_CANONICAL: dict[RateUnit, tuple[int, CanonicalUnit]] = {
    RateUnit.CENTS_PER_KWH: (-2, CanonicalUnit.RAND_PER_KWH),
    RateUnit.RAND_PER_KWH: (0, CanonicalUnit.RAND_PER_KWH),
    RateUnit.RAND_PER_DAY: (0, CanonicalUnit.RAND_PER_DAY),
    RateUnit.RAND_PER_MONTH: (0, CanonicalUnit.RAND_PER_MONTH),
}


class Rate(DomainModel):
    """A rate as printed: an exact value and its unit."""

    value: ExactDecimal
    unit: RateUnit

    @property
    def canonical_unit(self) -> CanonicalUnit:
        return _CANONICAL[self.unit][1]

    @property
    def canonical_value(self) -> Decimal:
        """The rate in rand per canonical unit; cents are shifted exactly, not divided."""
        shift = _CANONICAL[self.unit][0]
        with exact():
            return self.value.scaleb(shift)

    def charge(self, quantity: Decimal) -> Money:
        """The exact, unquantised charge for a quantity in the canonical unit.

        The engine uses this instead of multiplying Decimals itself, so that no charge can
        be rounded by the default decimal context.
        """
        return Money(rand=self.canonical_value) * quantity
