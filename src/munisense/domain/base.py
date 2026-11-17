"""Shared base classes for the domain: the strict Pydantic model and the root error.

Every domain model is strict (no type coercion), frozen and refuses unknown fields
(ADR-0004). A domain model may not declare a bare `Decimal` field, even inside a union, a
collection or a generic parameter such as `Cited[Decimal]`: plain `Decimal` lets Pydantic
accept a JSON float. Fields must use `munisense.domain.money.ExactDecimal`, which carries
`EXACT_DECIMAL_MARKER`. The check runs when the class is created, so a mistake fails at
import time.

This module sits outside the domain's layers so that every layer may use it.
"""

from decimal import Decimal
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict


class _ExactDecimalMarker:
    """Metadata that marks an `Annotated[Decimal, ...]` as validated exactly."""


EXACT_DECIMAL_MARKER = _ExactDecimalMarker()


class DomainError(Exception):
    """Root of every error the domain raises on purpose.

    Callers map these to refusals (for example RFC 9457 problems in the API). The domain
    raises them instead of guessing when data is missing, ambiguous or unsupported.
    """


class BareDecimalFieldError(TypeError):
    """A domain model declared a Decimal field without the exact-decimal validation."""


def _contains_bare_decimal(annotation: Any) -> bool:
    if annotation is Decimal:
        return True
    if get_origin(annotation) is Annotated:
        base, *metadata = get_args(annotation)
        if base is Decimal:
            return not any(item is EXACT_DECIMAL_MARKER for item in metadata)
        return _contains_bare_decimal(base)
    return any(_contains_bare_decimal(arg) for arg in get_args(annotation))


class DomainModel(BaseModel):
    """Base for domain value objects: strict, immutable, no extra fields, no bare Decimal."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for name, field in cls.model_fields.items():
            annotation = field.rebuild_annotation()
            if _contains_bare_decimal(annotation):
                msg = (
                    f"{cls.__name__}.{name} is a bare Decimal; use ExactDecimal so that "
                    "floats are refused"
                )
                raise BareDecimalFieldError(msg)
