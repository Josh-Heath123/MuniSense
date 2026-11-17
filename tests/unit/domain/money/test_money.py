"""Money, exact decimals and rates (P1-2). Values here are fixtures, not tariff data."""

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from munisense.domain.base import DomainModel
from munisense.domain.money import (
    CanonicalUnit,
    ExactDecimal,
    InexactArithmeticError,
    Money,
    Rate,
    RateUnit,
    exact,
)


class _Holder(DomainModel):
    value: ExactDecimal


# ------------------------------------------------------------------ floats are rejected


@pytest.mark.parametrize("bad", [1.1, 0.0, float("nan"), True, 1])
def test_exact_decimal_rejects_float_int_and_bool_in_python(bad: object) -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"value": bad})


@pytest.mark.parametrize("bad_json", ['{"value": 1.1}', '{"value": 1}', '{"value": 1e2}'])
def test_exact_decimal_rejects_json_numbers(bad_json: str) -> None:
    # Strict mode alone would accept a JSON float and convert it; ExactDecimal must not.
    with pytest.raises(ValidationError):
        _Holder.model_validate_json(bad_json)


def test_exact_decimal_rejects_a_python_string() -> None:
    # In Python, money is built from Decimal("..."), never parsed implicitly.
    with pytest.raises(ValidationError):
        _Holder.model_validate({"value": "1.10"})


@pytest.mark.parametrize("bad", ['"NaN"', '"Infinity"', '"-Infinity"', '"abc"'])
def test_exact_decimal_rejects_non_finite_or_garbage_json_strings(bad: str) -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate_json(f'{{"value": {bad}}}')


def test_exact_decimal_accepts_decimal_and_json_string_exactly() -> None:
    assert _Holder(value=Decimal("1.10")).value == Decimal("1.10")
    parsed = _Holder.model_validate_json('{"value": "234.6700"}')
    assert str(parsed.value) == "234.6700"  # printed precision kept


def test_money_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"rand": 10.5})


def test_rate_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Rate.model_validate({"value": 2.5, "unit": "c/kWh"})


def test_models_are_frozen_and_reject_extra_fields() -> None:
    money = Money(rand=Decimal("1"))
    with pytest.raises(ValidationError):
        money.rand = Decimal("2")  # type: ignore[misc]  # proving the runtime refusal
    with pytest.raises(ValidationError):
        Money.model_validate({"rand": Decimal("1"), "currency": "USD"})


def test_domain_model_is_strict_by_default() -> None:
    assert issubclass(DomainModel, BaseModel)
    assert DomainModel.model_config.get("strict") is True


# ----------------------------------------------------------------------------- money


def test_money_arithmetic_is_exact() -> None:
    total = Money(rand=Decimal("0.1")) + Money(rand=Decimal("0.2"))
    assert total == Money(rand=Decimal("0.3"))
    assert Money(rand=Decimal("5")) - Money(rand=Decimal("7.25")) == Money(rand=Decimal("-2.25"))
    assert Money(rand=Decimal("2.5")) * Decimal("3") == Money(rand=Decimal("7.5"))


def test_money_sum_of_nothing_is_zero() -> None:
    assert Money.sum([]) == Money.zero()


def test_money_multiplication_by_float_is_refused() -> None:
    with pytest.raises(TypeError):
        Money(rand=Decimal("1")) * 1.5  # type: ignore[operator]  # proving the refusal


def test_money_keeps_digits_until_a_rounding_policy_quantises() -> None:
    amount = Money(rand=Decimal("1.23456")) * Decimal("3")
    assert amount.rand == Decimal("3.70368")


# ----------------------------------------------------------------------- exactness


def test_exact_context_refuses_silent_rounding() -> None:
    with pytest.raises(InexactArithmeticError), exact():
        _ = Decimal(1) / Decimal(3)


def test_exact_context_allows_exact_division() -> None:
    with exact():
        assert Decimal("234.67") / Decimal(100) == Decimal("2.3467")


# ---------------------------------------------------------------------------- rates


@pytest.mark.parametrize(
    ("value", "unit", "canonical_value", "canonical_unit"),
    [
        ("234.67", RateUnit.CENTS_PER_KWH, "2.3467", CanonicalUnit.RAND_PER_KWH),
        ("2.3467", RateUnit.RAND_PER_KWH, "2.3467", CanonicalUnit.RAND_PER_KWH),
        ("12.50", RateUnit.RAND_PER_DAY, "12.50", CanonicalUnit.RAND_PER_DAY),
        ("350.00", RateUnit.RAND_PER_MONTH, "350.00", CanonicalUnit.RAND_PER_MONTH),
        ("1250", RateUnit.CENTS_PER_DAY, "12.50", CanonicalUnit.RAND_PER_DAY),
    ],
)
def test_rate_canonical_form(
    value: str, unit: RateUnit, canonical_value: str, canonical_unit: CanonicalUnit
) -> None:
    rate = Rate(value=Decimal(value), unit=unit)
    assert rate.canonical_value == Decimal(canonical_value)
    assert rate.canonical_unit is canonical_unit


def test_rate_keeps_its_printed_value_and_unit() -> None:
    rate = Rate.model_validate_json('{"value": "234.6700", "unit": "c/kWh"}')
    assert str(rate.value) == "234.6700"
    assert rate.unit is RateUnit.CENTS_PER_KWH


def test_unknown_rate_unit_is_refused() -> None:
    with pytest.raises(ValidationError):
        Rate.model_validate_json('{"value": "1", "unit": "R/kVA"}')


def test_rate_json_round_trip_is_exact() -> None:
    rate = Rate(value=Decimal("234.6700"), unit=RateUnit.CENTS_PER_KWH)
    assert Rate.model_validate_json(rate.model_dump_json()) == rate
    assert '"234.6700"' in rate.model_dump_json()
