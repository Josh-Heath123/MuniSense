"""Shared base classes for the domain: the strict Pydantic model and the root error.

Every domain model is strict (no type coercion), frozen and refuses unknown fields
(ADR-0004). This module sits outside the domain's layers so that every layer may use it.
"""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base for domain value objects: strict, immutable, no extra fields."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class DomainError(Exception):
    """Root of every error the domain raises on purpose.

    Callers map these to refusals (for example RFC 9457 problems in the API). The domain
    raises them instead of guessing when data is missing, ambiguous or unsupported.
    """
