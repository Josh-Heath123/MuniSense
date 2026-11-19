"""Canonical JSON for committed tariff files, defined on the text alone (ADR-0012, section 1).

A file is canonical when its text equals `json.dumps(json.loads(text), indent=2,
ensure_ascii=False)` followed by one final newline. Key order is whatever the file has: the
check never reorders, so it stays true for a file published years ago, whatever the models
have become since. Parsing refuses floats, `NaN`, `Infinity`, `-Infinity` and duplicate keys.

Validation through a model is a separate step (`munisense.provenance.publication`).
"""

import json
from typing import Any, NoReturn


class CanonicalJsonError(ValueError):
    """The text is not JSON, has a refused value, or is not in canonical form."""


def _refuse_float(text: str) -> NoReturn:
    msg = f"a JSON number with a fraction or exponent is refused (floats): {text[:40]}"
    raise CanonicalJsonError(msg)


def _refuse_constant(name: str) -> NoReturn:
    msg = f"the JSON constant {name} is refused"
    raise CanonicalJsonError(msg)


def _refuse_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        duplicate = next(key for key in keys if keys.count(key) > 1)
        msg = f"the key {duplicate!r} appears twice in one object"
        raise CanonicalJsonError(msg)
    return dict(pairs)


def parse(text: str) -> Any:  # JSON is any of six types
    """Parse strictly: no floats, no NaN or Infinity, no duplicate keys."""
    try:
        return json.loads(
            text,
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
            object_pairs_hook=_refuse_duplicates,
        )
    except json.JSONDecodeError as error:
        msg = f"not valid JSON: {error.msg} (line {error.lineno}, column {error.colno})"
        raise CanonicalJsonError(msg) from None


def dumps(value: object) -> str:
    """The canonical text of a JSON value: what `parse` reads back unchanged."""
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def check(text: str) -> Any:
    """Parse `text` strictly and refuse it unless it is already in canonical form."""
    value = parse(text)
    if dumps(value) != text:
        msg = "not in canonical form (two-space indentation, one final newline, no extra spaces)"
        raise CanonicalJsonError(msg)
    return value
