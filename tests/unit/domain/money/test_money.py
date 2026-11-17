"""Money, exact decimals and rates (P1-2). Values here are fixtures, not tariff data."""

from decimal import Decimal, localcontext

import pytest
from pydantic import BaseModel, ValidationError

from munisense.domain.base import DomainError, DomainModel
from munisense.domain.money import (
    CanonicalUnit,
    ExactDecimal,
    InexactArithmeticError,
    InvalidArithmeticError,
    Money,
    Rate,
    RateUnit,
    exact,
)


class _Holder(DomainModel):
    value: ExactDecimal


# More than the default context's 28 significant digits: the default context would round.
WIDE = Decimal("1" + "0" * 30 + ".01")


def _exact_reference(operation: str, a: Decimal, b: Decimal) -> Decimal:
    """Compute a reference result in an independent, very wide context."""
    with localcontext(prec=200):
        return {"+": a + b, "-": a - b, "*": a * b}[operation]


# ------------------------------------------------------------------ floats are rejected


@pytest.mark.parametrize("bad", [1.1, 0.0, float("nan"), True, 1])
def test_exact_decimal_rejects_float_int_and_bool_in_python(bad: object) -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"value": bad})


@pytest.mark.parametrize("bad", [1.1, 1])
def test_lax_validation_still_rejects_float_and_int(bad: object) -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate({"value": bad}, strict=False)


def test_money_constructor_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Money(rand=1.5)  # type: ignore[arg-type]  # mypy refuses this too (warn_unused_ignores)


def test_rate_constructor_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Rate(value=2.5, unit=RateUnit.CENTS_PER_KWH)  # type: ignore[arg-type]  # as above


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (Money, '{"rand": 1.5}'),
        (Money, '{"rand": 1}'),
        (Rate, '{"value": 2.5, "unit": "c/kWh"}'),
        (_Holder, '{"value": 1e2}'),
    ],
)
def test_json_numbers_are_rejected(model: type[BaseModel], payload: str) -> None:
    # Strict mode alone would accept a JSON float and convert it; ExactDecimal must not.
    with pytest.raises(ValidationError):
        model.model_validate_json(payload)


def test_exact_decimal_rejects_a_python_string() -> None:
    # In Python, money is built from Decimal("..."), never parsed implicitly.
    with pytest.raises(ValidationError):
        _Holder.model_validate({"value": "1.10"})


@pytest.mark.parametrize(
    "bad",
    [
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "abc",
        "",
        " 12.5",
        "12.5 ",
        "1_000",
        "+1",
        "1E+2",
        "1e-999999999",
        "١٢",  # Arabic-Indic digits
        ".5",
        "5.",
        "1" * 16,
        "0." + "1" * 13,
        "0." + "1" * 5000,
    ],
)
def test_json_strings_outside_the_plain_decimal_grammar_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _Holder.model_validate_json(f'{{"value": "{bad}"}}')


def test_validation_errors_do_not_echo_the_input() -> None:
    secret = "9" * 40 + "ACCOUNT"
    with pytest.raises(ValidationError) as caught:
        _Holder.model_validate_json(f'{{"value": "{secret}"}}')
    message = caught.value.errors()[0]["msg"]
    assert secret not in message
    assert "ACCOUNT" not in message


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")])
def test_non_finite_python_decimals_are_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        _Holder(value=bad)


def test_python_decimals_beyond_the_exact_context_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _Holder(value=Decimal("1" * 61))
    with pytest.raises(ValidationError):
        _Holder(value=Decimal("1e-999999999"))


def test_exact_decimal_accepts_decimal_and_json_string_exactly() -> None:
    assert _Holder(value=Decimal("1.10")).value == Decimal("1.10")
    parsed = _Holder.model_validate_json('{"value": "-234.6700"}')
    assert str(parsed.value) == "-234.6700"  # printed precision kept


def test_models_are_frozen_and_reject_extra_fields() -> None:
    money = Money(rand=Decimal("1"))
    with pytest.raises(ValidationError):
        money.rand = Decimal("2")  # type: ignore[misc]  # proving the runtime refusal
    with pytest.raises(ValidationError):
        Money.model_validate({"rand": Decimal("1"), "currency": "USD"})


def test_domain_model_is_strict_by_default() -> None:
    assert DomainModel.model_config.get("strict") is True


# ----------------------------------------------------------------------------- money


def test_money_arithmetic_is_exact() -> None:
    total = Money(rand=Decimal("0.1")) + Money(rand=Decimal("0.2"))
    assert total == Money(rand=Decimal("0.3"))
    assert Money(rand=Decimal("5")) - Money(rand=Decimal("7.25")) == Money(rand=Decimal("-2.25"))
    assert Money(rand=Decimal("2.5")) * Decimal("3") == Money(rand=Decimal("7.5"))


@pytest.mark.parametrize("operation", ["+", "-", "*"])
def test_money_arithmetic_beyond_28_digits_is_exact(operation: str) -> None:
    # The default decimal context keeps 28 digits and would round these results.
    a, b = WIDE, Decimal("0.001")
    x = Money(rand=a)
    result = {"+": lambda: x + Money(rand=b), "-": lambda: x - Money(rand=b)}.get(
        operation, lambda: x * b
    )()
    assert result.rand == _exact_reference(operation, a, b)
    assert len(result.rand.as_tuple().digits) > 28


def test_money_sum_adds_every_amount_exactly() -> None:
    amounts = [Money(rand=WIDE), Money(rand=Decimal("0.001")), Money(rand=Decimal("-0.5"))]
    assert Money.sum(amounts).rand == Decimal("9" * 30 + ".511")  # 10^30 + 0.011 - 0.5


def test_money_sum_of_nothing_is_zero() -> None:
    assert Money.sum([]) == Money.zero()


def test_money_arithmetic_that_would_round_is_refused() -> None:
    big = Money(rand=Decimal("9" * 40))
    with pytest.raises(InexactArithmeticError):
        _ = big * Decimal("1." + "1" * 30)


@pytest.mark.parametrize("bad", [1.5, 2, True])
def test_money_multiplication_by_a_non_decimal_is_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        Money(rand=Decimal("1")) * bad  # type: ignore[operator]  # proving the refusal


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")])
def test_money_multiplication_by_a_non_finite_decimal_is_refused(bad: Decimal) -> None:
    with pytest.raises(InvalidArithmeticError):
        Money(rand=Decimal("1")) * bad


def test_money_plus_a_non_money_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        Money(rand=Decimal("1")) + Decimal("1")
    with pytest.raises(TypeError):
        Money(rand=Decimal("1")) - Decimal("1")


def test_money_keeps_digits_until_a_rounding_policy_quantises() -> None:
    amount = Money(rand=Decimal("1.23456")) * Decimal("3")
    assert amount.rand == Decimal("3.70368")


# ----------------------------------------------------------------------- exactness


def test_exact_context_refuses_silent_rounding() -> None:
    with pytest.raises(InexactArithmeticError), exact():
        _ = Decimal(1) / Decimal(3)


def test_exact_context_refuses_division_by_zero() -> None:
    with pytest.raises(InvalidArithmeticError), exact():
        _ = Decimal(1) / Decimal(0)


def test_exact_context_refuses_invalid_operations() -> None:
    with pytest.raises(InvalidArithmeticError), exact():
        _ = Decimal(0) / Decimal(0)


def test_exact_context_refuses_floats() -> None:
    with pytest.raises(InvalidArithmeticError), exact():
        _ = Decimal(1.1)  # noqa: RUF032 - the float is the point of the test


def test_exact_context_errors_are_domain_errors() -> None:
    assert issubclass(InexactArithmeticError, DomainError)
    assert issubclass(InvalidArithmeticError, DomainError)


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
    ],
)
def test_rate_canonical_form(
    value: str, unit: RateUnit, canonical_value: str, canonical_unit: CanonicalUnit
) -> None:
    rate = Rate(value=Decimal(value), unit=unit)
    assert str(rate.canonical_value) == canonical_value  # same digits, not just equal
    assert rate.canonical_unit is canonical_unit


def test_every_rate_unit_has_a_canonical_form() -> None:
    for unit in RateUnit:
        assert Rate(value=Decimal("1"), unit=unit).canonical_unit in CanonicalUnit


def test_rate_charge_is_exact_beyond_28_digits() -> None:
    rate = Rate(value=Decimal("234.6789"), unit=RateUnit.CENTS_PER_KWH)
    quantity = Decimal("123456789012345.123456789")
    expected = _exact_reference("*", Decimal("2.346789"), quantity)
    assert rate.charge(quantity).rand == expected
    assert len(expected.as_tuple().digits) > 28


def test_rate_keeps_its_printed_value_and_unit() -> None:
    rate = Rate.model_validate_json('{"value": "234.6700", "unit": "c/kWh"}')
    assert str(rate.value) == "234.6700"
    assert rate.unit is RateUnit.CENTS_PER_KWH


@pytest.mark.parametrize("unit", ["R/kVA", "c/day", "c/kwh"])
def test_unknown_rate_unit_is_refused(unit: str) -> None:
    with pytest.raises(ValidationError):
        Rate.model_validate_json(f'{{"value": "1", "unit": "{unit}"}}')


def test_rate_json_round_trip_is_exact() -> None:
    rate = Rate(value=Decimal("234.6700"), unit=RateUnit.CENTS_PER_KWH)
    assert Rate.model_validate_json(rate.model_dump_json()) == rate
    assert '"234.6700"' in rate.model_dump_json()
