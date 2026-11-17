"""Exact decimals: the only number type for money, rates and quantities (ADR-0005).

`ExactDecimal` accepts a `Decimal` in Python and a plain decimal string in JSON. It rejects
`float`, `int` and `bool` everywhere, including JSON numbers, which Pydantic's strict mode
would otherwise convert silently. NaN and infinities are rejected.

JSON strings must match a strict ASCII grammar (`-?digits[.digits]`, bounded length): no
exponents, whitespace, underscores, `+` signs or non-ASCII digits, so a stored value always
reads the same as the text that was transcribed. Python-mode values must fit the exact
context below.

`exact()` is a decimal context that refuses any arithmetic that would round, divide by
zero or overflow. Quantisation happens only through a rounding policy, never as a side
effect of precision. Error messages never echo input values.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Strict, ValidationInfo

from munisense.domain.base import exact_decimal_validator
from munisense.domain.money.errors import InexactArithmeticError, InvalidArithmeticError

# Digits available to exact arithmetic. Inputs are far smaller (see the JSON grammar), so
# a product of two inputs is exact; anything that would still need rounding raises.
EXACT_PRECISION = 60
_EXPONENT_LIMIT = EXACT_PRECISION

# What a tariff document or an API caller may write: at most 15 integer digits and
# 12 decimal places.
MAX_INTEGER_DIGITS = 15
MAX_DECIMAL_PLACES = 12
_JSON_DECIMAL = re.compile(
    rf"-?[0-9]{{1,{MAX_INTEGER_DIGITS}}}(\.[0-9]{{1,{MAX_DECIMAL_PLACES}}})?", re.ASCII
)


@exact_decimal_validator
def _parse_input(value: object, info: ValidationInfo) -> object:
    # Pydantic turns a ValueError raised here into a ValidationError. Messages are fixed
    # text: they never contain the rejected value.
    if isinstance(value, bool | float | int):
        msg = f"{type(value).__name__} is not allowed here; use Decimal or a decimal string"
        raise ValueError(msg)
    if info.mode == "json" and isinstance(value, str):
        if not _JSON_DECIMAL.fullmatch(value):
            msg = (
                "not a plain decimal string (expected -?digits[.digits], at most "
                f"{MAX_INTEGER_DIGITS} integer digits and {MAX_DECIMAL_PLACES} decimals)"
            )
            raise ValueError(msg)
        return Decimal(value)
    return value


def _check_fits_exact_context(value: Decimal) -> Decimal:
    # NaN and infinities never reach this point: Pydantic's Decimal schema refuses them
    # (allow_inf_nan is off by default; tested).
    digits = len(value.as_tuple().digits)
    if digits > EXACT_PRECISION or abs(value.adjusted()) > _EXPONENT_LIMIT:
        msg = f"must fit in {EXACT_PRECISION} significant digits"
        raise ValueError(msg)
    return value


ExactDecimal = Annotated[
    Decimal,
    BeforeValidator(_parse_input),
    Strict(),
    AfterValidator(_check_fits_exact_context),
]
"""A finite Decimal built from a Decimal (Python) or a plain string (JSON), never a float."""


_TRAPS = [
    Inexact,
    Rounded,
    InvalidOperation,
    DivisionByZero,
    Overflow,
    Underflow,
    Subnormal,
    Clamped,
    FloatOperation,
]


@contextmanager
def exact() -> Iterator[Context]:
    """Run decimal arithmetic that raises a domain error instead of rounding or guessing.

    Rounding raises `InexactArithmeticError`. Division by zero, invalid operations,
    overflow and mixing in floats raise `InvalidArithmeticError`.
    """
    context = Context(prec=EXACT_PRECISION, traps=_TRAPS)
    try:
        with localcontext(context) as active:
            yield active
    except DecimalException as error:
        if isinstance(error, Inexact | Rounded):
            raise InexactArithmeticError("the result would need rounding") from error
        raise InvalidArithmeticError(
            f"invalid decimal operation ({type(error).__name__})"
        ) from error
