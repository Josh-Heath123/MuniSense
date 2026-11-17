"""Errors raised by the money package."""

from munisense.domain.base import DomainError


class InexactArithmeticError(DomainError):
    """A calculation would have rounded outside a named rounding policy."""


class InvalidArithmeticError(DomainError):
    """A calculation divided by zero, overflowed, mixed in a float or was otherwise invalid."""
