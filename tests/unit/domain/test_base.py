"""The domain base model refuses bare Decimal fields (P1-3)."""

from decimal import Decimal

import pytest

from munisense.domain.base import BareDecimalFieldError, DomainModel
from munisense.domain.citations import Cited
from munisense.domain.money import ExactDecimal


@pytest.mark.parametrize(
    "annotation",
    [Decimal, Decimal | None, list[Decimal], dict[str, Decimal], tuple[int, Decimal]],
)
def test_a_bare_decimal_field_is_refused_when_the_class_is_created(annotation: object) -> None:
    with pytest.raises(BareDecimalFieldError):
        type("Bad", (DomainModel,), {"__annotations__": {"value": annotation}})


def test_a_generic_parameterised_with_bare_decimal_is_refused() -> None:
    with pytest.raises(BareDecimalFieldError):
        Cited[Decimal]


@pytest.mark.parametrize(
    "annotation", [ExactDecimal, ExactDecimal | None, tuple[ExactDecimal, ...], int, str]
)
def test_exact_decimal_and_other_fields_are_allowed(annotation: object) -> None:
    type("Good", (DomainModel,), {"__annotations__": {"value": annotation}})
