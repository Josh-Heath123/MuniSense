"""Errors raised by the billing package."""

from munisense.domain.base import DomainError


class UnsupportedConsumptionError(DomainError):
    """The consumption profile is of a kind the engine cannot evaluate yet."""


class PeriodOutsideVersionError(DomainError):
    """The billing period is not wholly inside the tariff version's effective range."""


class PeriodCrossesSeasonError(DomainError):
    """The period crosses a season boundary of a seasonal component (splitting is P1-13)."""


class NonMonthlyPeriodError(DomainError):
    """The period is not one calendar month but the tariff has monthly values."""


class UnsupportedPriceBasisError(DomainError):
    """The tariff prints prices including VAT, which the engine does not support yet."""


class FreeBasicEligibilityRequiredError(DomainError):
    """The tariff has a free basic allocation but the customer's eligibility was not given."""


class FreeBasicNotOfferedError(DomainError):
    """The customer is marked eligible for a free basic allocation the tariff does not have."""
