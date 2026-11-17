"""Money in South African rand, exact and unquantised until a rounding policy says so."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Self

from munisense.domain.base import DomainModel
from munisense.domain.money.errors import InvalidArithmeticError
from munisense.domain.money.exact import ExactDecimal, exact
from munisense.domain.money.rounding import Quantisation


class Money(DomainModel):
    """An amount in rand (ZAR). Arithmetic is exact; nothing is rounded here."""

    rand: ExactDecimal

    @classmethod
    def zero(cls) -> Self:
        return cls(rand=Decimal(0))

    @classmethod
    def sum(cls, amounts: Iterable["Money"]) -> "Money":
        total = Money.zero()
        for amount in amounts:
            total = total + amount
        return total

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        with exact():
            return Money(rand=self.rand + other.rand)

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        with exact():
            return Money(rand=self.rand - other.rand)

    def quantised(self, quantisation: Quantisation) -> "Money":
        """This amount rounded at a quantisation point named by a rounding policy."""
        return Money(rand=quantisation.apply(self.rand))

    def __mul__(self, factor: Decimal) -> "Money":
        _require_finite_decimal(factor)
        with exact():
            return Money(rand=self.rand * factor)


def _require_finite_decimal(factor: object) -> None:
    # The type checker already refuses a float here; this guards untyped callers too.
    if not isinstance(factor, Decimal):
        msg = f"Money can only be multiplied by a Decimal, not {type(factor).__name__}"
        raise TypeError(msg)
    if not factor.is_finite():
        msg = "Money can only be multiplied by a finite Decimal"
        raise InvalidArithmeticError(msg)
