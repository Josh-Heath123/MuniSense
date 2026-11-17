"""Money in South African rand, exact and unquantised until a rounding policy says so."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Self

from munisense.domain.base import DomainModel
from munisense.domain.money.exact import ExactDecimal, exact


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

    def __add__(self, other: "Money") -> "Money":
        with exact():
            return Money(rand=self.rand + other.rand)

    def __sub__(self, other: "Money") -> "Money":
        with exact():
            return Money(rand=self.rand - other.rand)

    def __mul__(self, factor: Decimal) -> "Money":
        _require_decimal(factor)
        with exact():
            return Money(rand=self.rand * factor)


def _require_decimal(factor: object) -> None:
    # The type checker already refuses a float here; this guards untyped callers too.
    if not isinstance(factor, Decimal):
        msg = f"Money can only be multiplied by a Decimal, not {type(factor).__name__}"
        raise TypeError(msg)
