"""Errors raised by the billing package."""

from munisense.domain.base import DomainError


class UnsupportedConsumptionError(DomainError):
    """The consumption profile is of a kind the engine cannot evaluate yet."""


class PeriodOutsideVersionError(DomainError):
    """The billing period is not wholly inside the tariff version's effective range."""


class NonMonthlyPeriodError(DomainError):
    """The period is not one calendar month but the tariff has monthly values."""


class UnsupportedPriceBasisError(DomainError):
    """The tariff prints prices including VAT, which the engine does not support yet."""
