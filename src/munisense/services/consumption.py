"""Reading consumption input from JSON (P4-4).

JSON parsers, Pydantic's included, silently keep the last of two equal keys, so a profile
naming "peak" twice would be billed on one of the two figures without a word. Interfaces
read consumption JSON here, never with `validate_json` alone.
"""

import json

from pydantic import TypeAdapter

from munisense.domain.billing import ConsumptionProfile, PeriodTotal, TimeOfUseBuckets

_PROFILE: TypeAdapter[PeriodTotal | TimeOfUseBuckets] = TypeAdapter(ConsumptionProfile)


class DuplicateKeyError(ValueError):
    """The JSON names the same key twice in one object; it is refused, not guessed."""


def _refuse_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        twice = sorted({key for key in keys if keys.count(key) > 1})
        msg = f"a key is given twice: {', '.join(twice)}"
        raise DuplicateKeyError(msg)
    return dict(pairs)


def parse_consumption_json(text: str) -> PeriodTotal | TimeOfUseBuckets:
    """A consumption profile from JSON text, validated as the model validates JSON, with
    any key given twice (at any depth) refused."""
    profile = _PROFILE.validate_json(text)
    json.loads(text, object_pairs_hook=_refuse_duplicates)  # valid JSON by now
    return profile
