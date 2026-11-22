"""Reading consumption input from JSON (P4-4).

JSON parsers, Pydantic's included, silently keep the last of two equal keys, so a profile
naming "peak" twice would be billed on one of the two figures without a word. Interfaces
read consumption JSON here, never with `validate_json` alone, and map
`ConsumptionJsonError` to a refusal with a stable code (P5).

Nothing here repeats the input. Pydantic's own messages name field paths, which can be
keys the client chose (any length, control characters included), so a `ValidationError`
never leaves this module: it becomes a `ConsumptionJsonError` with fixed text and only
Pydantic's error type codes (such as `missing` or `extra_forbidden`). Each refusal is
raised outside the `except` block that saw the original error, so no exception chain
carries the input either.
"""

import json

from pydantic import ConfigDict, TypeAdapter, ValidationError

from munisense.domain.billing import ConsumptionProfile, PeriodTotal, TimeOfUseBuckets

_PROFILE: TypeAdapter[PeriodTotal | TimeOfUseBuckets] = TypeAdapter(
    ConsumptionProfile, config=ConfigDict(strict=True, hide_input_in_errors=True)
)


class ConsumptionJsonError(ValueError):
    """Consumption JSON refused. The message is fixed text; `codes` are Pydantic's error
    type codes (never paths or values), empty for a refusal of this module's own."""

    def __init__(self, message: str, codes: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.codes = codes


class DuplicateKeyError(ConsumptionJsonError):
    """The JSON names the same key twice in one object; it is refused, not guessed."""


def _refuse_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            msg = "a key is given twice in one JSON object"
            raise DuplicateKeyError(msg)
        seen.add(key)
    return dict(pairs)


def _validate(text: str) -> PeriodTotal | TimeOfUseBuckets | tuple[str, ...]:
    """The profile, or the error type codes of why it is not one."""
    try:
        return _PROFILE.validate_json(text)
    except ValidationError as error:
        return tuple(sorted({str(e["type"]) for e in error.errors(include_input=False)}))


def _has_duplicates(text: str) -> bool | None:
    """True if a key is given twice; None if the text cannot be read a second time."""
    try:
        json.loads(text, object_pairs_hook=_refuse_duplicates)
    except DuplicateKeyError:
        return True
    except (ValueError, RecursionError):  # JSONDecodeError, huge integers, deep nesting
        return None
    return False


def parse_consumption_json(text: str) -> PeriodTotal | TimeOfUseBuckets:
    """A consumption profile from JSON text, validated as the model validates JSON, with
    any key given twice (at any depth) refused. Raises only `ConsumptionJsonError`."""
    result = _validate(text)
    if isinstance(result, tuple):
        if "union_tag_invalid" in result:
            msg = "the consumption kind is not one MuniSense knows"
        else:
            msg = "the consumption input is not valid"
        raise ConsumptionJsonError(msg, result)
    duplicates = _has_duplicates(text)
    if duplicates is None:
        msg = "the JSON could not be read a second time to check for repeated keys"
        raise ConsumptionJsonError(msg)
    if duplicates:
        msg = "a key is given twice in one JSON object"
        raise DuplicateKeyError(msg)
    return result
