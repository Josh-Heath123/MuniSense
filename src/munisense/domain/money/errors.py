"""Errors raised by the money package."""

from munisense.domain.base import DomainError


class InexactArithmeticError(DomainError):
    """A calculation would have rounded outside a named rounding policy."""


class InvalidArithmeticError(DomainError):
    """A calculation divided by zero, overflowed, mixed in a float or was otherwise invalid."""


class NoVatRateError(DomainError):
    """No VAT rate is recorded for (all of) the period."""


class VatRateChangesError(DomainError):
    """The VAT rate changes inside the period; it must be split first."""
