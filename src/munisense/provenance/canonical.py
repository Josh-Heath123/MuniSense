"""Canonical JSON for committed tariff files, defined on the text alone (ADR-0012, section 1).

A file is canonical when its bytes are UTF-8 (no byte-order mark) and its text equals
`json.dumps(json.loads(text), indent=2, ensure_ascii=False)` followed by one final newline.
Key order is whatever the file has: the check never reorders, so it stays true for a file
published years ago, whatever the models have become since.

Parsing refuses floats, `NaN`, `Infinity`, `-Infinity`, duplicate keys, integers longer
than `MAX_INTEGER_DIGITS` and nesting deeper than Python can parse. Writing refuses the same
values, and text that cannot be encoded as UTF-8 (lone surrogates). Every refusal is a
`CanonicalJsonError`.

Validation through a model is a separate step (`munisense.provenance.publication`).
"""

import json
from typing import Any, NoReturn

from munisense.provenance.errors import CanonicalJsonError

__all__ = ["MAX_INTEGER_DIGITS", "CanonicalJsonError", "check", "check_bytes", "dumps", "parse"]

MAX_INTEGER_DIGITS = 30
"""Far beyond any page number or count in a tariff file; decimals are strings."""


def _refuse_float(text: str) -> NoReturn:
    msg = f"a JSON number with a fraction or exponent is refused (floats): {text[:40]}"
    raise CanonicalJsonError(msg)


def _bounded_int(text: str) -> int:
    if len(text.lstrip("-")) > MAX_INTEGER_DIGITS:
        msg = f"an integer longer than {MAX_INTEGER_DIGITS} digits is refused"
        raise CanonicalJsonError(msg)
    return int(text)


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
    """Parse strictly: no floats, NaN, Infinity, duplicate keys or overlong integers."""
    try:
        return json.loads(
            text,
            parse_float=_refuse_float,
            parse_int=_bounded_int,
            parse_constant=_refuse_constant,
            object_pairs_hook=_refuse_duplicates,
        )
    except json.JSONDecodeError as error:
        msg = f"not valid JSON: {error.msg} (line {error.lineno}, column {error.colno})"
        raise CanonicalJsonError(msg) from None
    except RecursionError:
        msg = "nested too deeply to parse"
        raise CanonicalJsonError(msg) from None


def dumps(value: object) -> str:
    """The canonical text of a JSON value, refusing anything `parse` would refuse."""
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        text.encode("utf-8")
    except UnicodeEncodeError:  # before ValueError, of which it is a subclass
        msg = "cannot write text that is not valid UTF-8 (a lone surrogate)"
        raise CanonicalJsonError(msg) from None
    except ValueError as error:  # NaN or Infinity (allow_nan=False)
        msg = f"cannot write this value as canonical JSON: {error}"
        raise CanonicalJsonError(msg) from None
    except (TypeError, RecursionError) as error:
        msg = f"cannot write this value as canonical JSON: {type(error).__name__}"
        raise CanonicalJsonError(msg) from None
    parse(text)  # refuses floats and overlong integers on the way out too
    return text


def check(text: str) -> Any:
    """Parse `text` strictly and refuse it unless it is already in canonical form."""
    value = parse(text)
    if dumps(value) != text:
        msg = "not in canonical form (two-space indentation, one final newline, no extra spaces)"
        raise CanonicalJsonError(msg)
    return value


def check_bytes(data: bytes) -> Any:
    """`check` for a file's bytes: strict UTF-8, no byte-order mark."""
    if data.startswith(b"\xef\xbb\xbf"):
        msg = "a byte-order mark is refused"
        raise CanonicalJsonError(msg)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "not valid UTF-8"
        raise CanonicalJsonError(msg) from None
    return check(text)
