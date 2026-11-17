"""Errors raised by the citations package."""

from munisense.domain.base import DomainError


class NoStatusesError(DomainError):
    """A summary status was asked for an empty set of values."""


class UnparameterisedCitedError(DomainError):
    """`Cited` was used without a type parameter, so its value would accept anything."""
