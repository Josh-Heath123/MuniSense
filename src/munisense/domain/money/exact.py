"""Exact decimals: the only number type for money, rates and quantities (ADR-0005).

`ExactDecimal` accepts a `Decimal` in Python and a string in JSON. It rejects `float`,
`int` and `bool` everywhere, including JSON numbers, which Pydantic's strict mode would
otherwise convert silently. NaN and infinities are rejected.

`exact()` is a decimal context that refuses any arithmetic that would round. Quantisation
happens only through a rounding policy, never as a side effect of precision.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext
from typing import Annotated

from pydantic import AllowInfNan, BeforeValidator, Strict, ValidationInfo

from munisense.domain.money.errors import InexactArithmeticError

# Enough digits for any bill: values are at most about 12 integer digits and 10 decimals,
# and a product of two of them stays far below this. Anything that still needs rounding
# raises instead.
EXACT_PRECISION = 60


def _refuse_inexact_input(value: object, info: ValidationInfo) -> object:
    # Pydantic turns a ValueError raised here into a ValidationError.
    if isinstance(value, bool | float | int):
        msg = f"{type(value).__name__} is not allowed here; use Decimal or a decimal string"
        raise ValueError(msg)
    if info.mode == "json" and isinstance(value, str):
        # JSON carries exact decimals as strings ("234.6700"); parse them without loss.
        try:
            return Decimal(value)
        except InvalidOperation as error:
            msg = f"{value!r} is not a decimal number"
            raise ValueError(msg) from error
    return value


ExactDecimal = Annotated[
    Decimal,
    BeforeValidator(_refuse_inexact_input),
    Strict(),
    AllowInfNan(False),
]
"""A finite Decimal built from a Decimal (Python) or a string (JSON), never a float."""


@contextmanager
def exact() -> Iterator[Context]:
    """Run decimal arithmetic that raises `InexactArithmeticError` instead of rounding."""
    context = Context(prec=EXACT_PRECISION, traps=[Inexact, Rounded, InvalidOperation])
    try:
        with localcontext(context) as active:
            yield active
    except (Inexact, Rounded) as error:
        raise InexactArithmeticError(str(error)) from error
