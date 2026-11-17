"""Shared base classes for the domain: the strict Pydantic model and the root error.

Every domain model is strict (no type coercion), frozen and refuses unknown fields
(ADR-0004). It also may not accept a float anywhere, directly or nested:

- Pydantic's plain `Decimal` schema accepts JSON floats even in strict mode, so every
  decimal must be validated by `munisense.domain.money.ExactDecimal`.
- A `float` field, or an untyped (`Any`) field, would let a float in as well.

The check walks the model's compiled core schema, which is what Pydantic actually
validates with, so type aliases, forward references, dataclasses and nested models are all
covered. It runs when the model is complete (`__pydantic_on_complete__`, also after a
`model_rebuild`), so a mistake fails at import time. An unparameterised generic such as
`Cited` is exempt at definition time, but refuses to validate anything (see `Cited`).

This module sits outside the domain's layers so that every layer may use it, and imports
nothing from them (import-linter rule 1c).
"""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

EXACT_VALIDATOR_ATTRIBUTE = "__munisense_exact_decimal__"
"""Set to True on the one validator function that parses decimals exactly."""

_FUNCTION_SCHEMAS = frozenset(
    {"function-before", "function-after", "function-wrap", "function-plain"}
)
_UNSAFE_SCHEMAS = frozenset({"decimal", "float", "any"})


class DomainError(Exception):
    """Root of every error the domain raises on purpose.

    Callers map these to refusals (for example RFC 9457 problems in the API). The domain
    raises them instead of guessing when data is missing, ambiguous or unsupported.
    """


class UnsafeNumberFieldError(TypeError):
    """A domain model could accept a float: a bare Decimal, a float or an untyped field."""


def exact_decimal_validator[F: Callable[..., object]](function: F) -> F:
    """Mark the validator that makes a Decimal field safe (used by `ExactDecimal` only)."""
    setattr(function, EXACT_VALIDATOR_ATTRIBUTE, True)
    return function


def _is_exact_validator(schema: dict[str, object]) -> bool:
    if schema.get("type") not in _FUNCTION_SCHEMAS:
        return False
    holder = schema.get("function")
    function = holder.get("function") if isinstance(holder, dict) else None
    return getattr(function, EXACT_VALIDATOR_ATTRIBUTE, False) is True


def unsafe_number_schemas(schema: object) -> list[str]:
    """Return the core-schema types in `schema` that could accept a float."""
    found: list[str] = []
    if isinstance(schema, dict):
        if _is_exact_validator(schema):
            return found  # everything below is validated exactly
        kind = schema.get("type")
        if isinstance(kind, str) and kind in _UNSAFE_SCHEMAS:
            found.append(kind)
        for key, value in schema.items():
            if key != "cls":  # the model class itself, not a schema
                found += unsafe_number_schemas(value)
    elif isinstance(schema, list | tuple):
        for item in schema:
            found += unsafe_number_schemas(item)
    return found


class DomainModel(BaseModel):
    """Base for domain value objects: strict, immutable, no extra fields, no float path."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    @classmethod
    def __pydantic_on_complete__(cls) -> None:
        if cls.__pydantic_generic_metadata__["parameters"]:
            return  # an unparameterised generic; its parameterisations are checked
        unsafe = unsafe_number_schemas(cls.__pydantic_core_schema__)
        if unsafe:
            msg = (
                f"{cls.__name__} could accept a float through a {', '.join(sorted(set(unsafe)))} "
                "schema; use ExactDecimal and concrete types"
            )
            raise UnsafeNumberFieldError(msg)
