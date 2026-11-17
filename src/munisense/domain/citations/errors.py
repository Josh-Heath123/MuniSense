"""Errors raised by the citations package."""

from munisense.domain.base import DomainError


class NoStatusesError(DomainError):
    """A summary status was asked for an empty set of values."""
