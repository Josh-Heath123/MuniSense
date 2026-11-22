"""Reading consumption input from JSON (P4-4).

JSON parsers, Pydantic's included, silently keep the last of two equal keys, so a profile
naming "peak" twice would be billed on one of the two figures without a word. Interfaces
read consumption JSON here, never with `validate_json` alone, and map both `ValidationError`
and `ConsumptionJsonError` to a refusal with a stable code (P5).

Nothing here repeats the input: Pydantic's messages hide it (`hide_input_in_errors`, which
affects `str(exc)` only; `exc.errors()` still holds the raw input and must never be shown),
an unknown profile kind (which Pydantic would name) becomes a fixed-text refusal here, and
this module's own messages are fixed text.
"""

import json

from pydantic import ConfigDict, TypeAdapter, ValidationError

from munisense.domain.billing import ConsumptionProfile, PeriodTotal, TimeOfUseBuckets

# The adapter's own config decides how a union's errors are shown; the models' config is
# not inherited here, so input hiding is set again.
_PROFILE: TypeAdapter[PeriodTotal | TimeOfUseBuckets] = TypeAdapter(
    ConsumptionProfile, config=ConfigDict(strict=True, hide_input_in_errors=True)
)


class ConsumptionJsonError(ValueError):
    """Consumption JSON refused for a reason the model cannot see. Fixed text only."""


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


def parse_consumption_json(text: str) -> PeriodTotal | TimeOfUseBuckets:
    """A consumption profile from JSON text, validated as the model validates JSON, with
    any key given twice (at any depth) refused. Raises only `ValidationError` or
    `ConsumptionJsonError`, neither repeating the input."""
    try:
        profile = _PROFILE.validate_json(text)
    except ValidationError as error:
        # Pydantic names an unknown union tag in its message even with input hidden.
        if any(e["type"] == "union_tag_invalid" for e in error.errors(include_input=False)):
            msg = "the consumption kind is not one MuniSense knows"
            raise ConsumptionJsonError(msg) from None
        raise
    try:
        json.loads(text, object_pairs_hook=_refuse_duplicates)
    except json.JSONDecodeError:
        msg = "the JSON could not be read a second time to check for repeated keys"
        raise ConsumptionJsonError(msg) from None
    return profile
