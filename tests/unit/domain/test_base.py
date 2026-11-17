"""The domain base model refuses any field that could accept a float (P1-3)."""

import dataclasses
import importlib
import inspect
import pkgutil
from decimal import Decimal
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, PlainValidator

import munisense.domain
from munisense.domain.base import DomainModel, UnsafeNumberFieldError, unsafe_number_schemas
from munisense.domain.citations import Cited
from munisense.domain.money import ExactDecimal

type DecimalAlias = Decimal
type DecimalListAlias = list[Decimal]
type ExactAlias = ExactDecimal


@dataclasses.dataclass(frozen=True)
class _DataclassWithDecimal:
    amount: Decimal


class _PlainModelWithDecimal(BaseModel):
    amount: Decimal


@pytest.mark.parametrize(
    "annotation",
    [
        Decimal,
        Decimal | None,
        list[Decimal],
        dict[str, Decimal],
        tuple[int, Decimal],
        float,
        float | None,
        Any,
        DecimalAlias,
        DecimalListAlias,
        _DataclassWithDecimal,
        _PlainModelWithDecimal,
        Annotated[ExactDecimal, PlainValidator(Decimal)],  # replaces the exact validator
    ],
)
def test_a_field_that_could_accept_a_float_is_refused(annotation: object) -> None:
    with pytest.raises(UnsafeNumberFieldError):
        type("Bad", (DomainModel,), {"__annotations__": {"value": annotation}})


@pytest.mark.parametrize("parameter", [Decimal, float])
def test_a_generic_parameterised_unsafely_is_refused(parameter: type) -> None:
    with pytest.raises(UnsafeNumberFieldError):
        Cited[parameter]  # type: ignore[valid-type]


def test_a_forward_reference_resolved_later_is_checked_on_rebuild() -> None:
    namespace: dict[str, object] = {}

    class Later(DomainModel):
        value: "Amount"  # type: ignore[name-defined]  # noqa: F821 - resolved below

    namespace["Amount"] = Decimal
    with pytest.raises(UnsafeNumberFieldError):
        Later.model_rebuild(_types_namespace=namespace)


@pytest.mark.parametrize(
    "annotation", [ExactDecimal, ExactDecimal | None, tuple[ExactDecimal, ...], ExactAlias, int]
)
def test_exact_decimal_and_other_fields_are_allowed(annotation: object) -> None:
    type("Good", (DomainModel,), {"__annotations__": {"value": annotation}})


def test_every_domain_model_in_the_package_is_safe() -> None:
    # Covers models completed after import (rebuilds) as well as at class creation.
    models = []
    for info in pkgutil.walk_packages(munisense.domain.__path__, prefix="munisense.domain."):
        module = importlib.import_module(info.name)
        models += [
            obj
            for obj in vars(module).values()
            if inspect.isclass(obj)
            and issubclass(obj, DomainModel)
            and obj is not DomainModel
            and not obj.__pydantic_generic_metadata__["parameters"]
        ]
    assert models
    for model in models:
        assert unsafe_number_schemas(model.__pydantic_core_schema__) == [], model.__name__
