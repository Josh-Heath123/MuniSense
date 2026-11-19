"""Canonical JSON is defined on the text alone (P2-4, ADR-0012 section 1)."""

import pytest

from munisense.provenance import canonical
from munisense.provenance.canonical import CanonicalJsonError

GOOD = '{\n  "b": 1,\n  "a": [\n    "é",\n    true,\n    null\n  ]\n}\n'


def test_canonical_text_is_accepted_and_keeps_its_key_order() -> None:
    value = canonical.check(GOOD)
    assert list(value) == ["b", "a"]
    assert canonical.dumps(value) == GOOD


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"x": 1.5}', "floats"),
        ('{"x": 1e3}', "floats"),
        ('{"x": 1E-2}', "floats"),
        ('{"x": NaN}', "NaN is refused"),
        ('{"x": Infinity}', "Infinity is refused"),
        ('{"x": -Infinity}', "-Infinity is refused"),
        ('{"x": 1, "x": 2}', "'x' appears twice"),
        ('{"a": {"y": 1, "y": 1}}', "'y' appears twice"),
        ('{"x": ', "not valid JSON"),
        ("", "not valid JSON"),
    ],
)
def test_refused_values_are_refused_on_parse(text: str, message: str) -> None:
    with pytest.raises(CanonicalJsonError, match=message):
        canonical.parse(text)


@pytest.mark.parametrize(
    "text",
    [
        GOOD.removesuffix("\n"),
        GOOD + "\n",
        GOOD.replace("\n  ", "\n    "),
        GOOD.replace('"b": 1', '"b" : 1'),
        GOOD.replace('"b": 1,', '"b": 1, '),
        GOOD.replace("\n", "\r\n"),
        GOOD.replace("é", "\\u00e9"),
        '{"b": 1, "a": ["é", true, null]}\n',
        chr(0xFEFF) + GOOD,  # a byte-order mark,
    ],
)
def test_other_formatting_of_the_same_value_is_not_canonical(text: str) -> None:
    with pytest.raises(CanonicalJsonError, match=r"canonical form|not valid JSON"):
        canonical.check(text)


def test_integers_and_strings_are_allowed() -> None:
    assert canonical.check('{\n  "page": 4,\n  "rate": "3.3700"\n}\n') == {
        "page": 4,
        "rate": "3.3700",
    }
