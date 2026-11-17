"""Errors raised by the money package."""

from munisense.domain.base import DomainError


class InexactArithmeticError(DomainError):
    """A calculation would have rounded outside a named rounding policy."""
