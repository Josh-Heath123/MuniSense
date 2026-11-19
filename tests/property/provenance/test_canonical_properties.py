"""Canonical JSON, for any JSON value without floats (P2-4).

Re-ordered keys are kept by design (the check never reorders); in a published file they are
caught by P2-9's no-change check.
"""

import json

from hypothesis import given
from hypothesis import strategies as st

from munisense.provenance import canonical
from munisense.provenance.canonical import CanonicalJsonError

scalars = st.none() | st.booleans() | st.integers() | st.text()
values = st.recursive(
    scalars,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(), inner, max_size=4),
    max_leaves=20,
)


@given(values)
def test_canonical_text_round_trips(value: object) -> None:
    text = canonical.dumps(value)
    assert canonical.check(text) == value


@given(values, st.sampled_from(["compact", "indent", "no-newline", "extra-newline", "ascii"]))
def test_changes_of_whitespace_or_formatting_are_caught(value: object, change: str) -> None:
    text = canonical.dumps(value)
    changed = {
        "compact": json.dumps(value, ensure_ascii=False) + "\n",
        "indent": json.dumps(value, indent=4, ensure_ascii=False) + "\n",
        "no-newline": text.removesuffix("\n"),
        "extra-newline": text + "\n",
        "ascii": json.dumps(value, indent=2, ensure_ascii=True) + "\n",
    }[change]
    if changed == text:  # the change did nothing for this value (for example, a scalar)
        return
    try:
        canonical.check(changed)
    except CanonicalJsonError:
        return
    raise AssertionError(changed)
