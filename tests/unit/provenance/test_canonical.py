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


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"x": 1.5}, "floats"),
        ({"x": float("nan")}, "cannot write"),
        ({"x": float("inf")}, "cannot write"),
        ({"x": "\ud800"}, "lone surrogate"),
        ({"x": object()}, "TypeError"),
        ({"x": 10**31}, "longer than 30 digits"),
    ],
)
def test_the_writer_refuses_what_the_parser_refuses(value: object, message: str) -> None:
    with pytest.raises(CanonicalJsonError, match=message):
        canonical.dumps(value)


def test_an_overlong_integer_is_refused_on_parse() -> None:
    with pytest.raises(CanonicalJsonError, match="longer than 30 digits"):
        canonical.parse('{"x": ' + "9" * 5000 + "}")


def test_very_deep_nesting_is_a_canonical_error() -> None:
    with pytest.raises(CanonicalJsonError, match="nested too deeply"):
        canonical.parse("[" * 100_000 + "]" * 100_000)


@pytest.mark.parametrize(
    "text",
    ['{"x": -0}\n', '{\n  "x": "\\/"\n}\n', "   \n"],
)
def test_more_non_canonical_forms(text: str) -> None:
    with pytest.raises(CanonicalJsonError, match=r"canonical form|not valid JSON"):
        canonical.check(text)


def test_an_escaped_lone_surrogate_is_refused() -> None:
    with pytest.raises(CanonicalJsonError, match="lone surrogate"):
        canonical.check('{\n  "x": "\\ud800"\n}\n')


@pytest.mark.parametrize("text", ["{}\n", "[]\n", "1\n", '"x"\n', "null\n"])
def test_empty_containers_and_scalars_are_canonical_json(text: str) -> None:
    assert canonical.dumps(canonical.check(text)) == text


def test_check_bytes_refuses_a_bom_and_invalid_utf8() -> None:
    assert canonical.check_bytes(b"{}\n") == {}
    with pytest.raises(CanonicalJsonError, match="byte-order mark"):
        canonical.check_bytes(b"\xef\xbb\xbf{}\n")
    with pytest.raises(CanonicalJsonError, match="not valid UTF-8"):
        canonical.check_bytes(b'{"x": "\xff"}\n')
