"""Errors raised by the billing package."""

from munisense.domain.base import DomainError


class UnsupportedConsumptionError(DomainError):
    """The consumption profile is of a kind the engine cannot evaluate yet."""
