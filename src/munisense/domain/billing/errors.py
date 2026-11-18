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


class IncompatibleVersionsError(DomainError):
    """The tariff versions given for a period are empty, overlap, or belong to different
    tariffs."""


class PrepaidNotSupportedError(DomainError):
    """The prepaid purchase needs something not built yet (for example free tokens)."""


class PurchaseTooSmallError(DomainError):
    """The purchase does not cover the fixed charges deducted from it."""


class PurchasesNotInOneMonthError(DomainError):
    """The purchases of a month are not in one calendar month, or not in order."""


class InvalidPurchaseError(DomainError):
    """The purchase's inputs are impossible (a negative amount, kWh with no purchase)."""


class PrepaidPrecisionError(DomainError):
    """The month's kWh so far or a block threshold is finer than the prepaid kWh step."""
