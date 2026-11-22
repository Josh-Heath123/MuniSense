"""Reading consumption JSON with duplicate keys refused (P4-4). Values here are fixtures."""

import json
import time
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from munisense.domain.billing import ConsumptionProfile, TimeOfUseBuckets
from munisense.domain.tariffs import TouPeriod
from munisense.services.consumption import (
    ConsumptionJsonError,
    DuplicateKeyError,
    parse_consumption_json,
)

PROFILE = TypeAdapter[ConsumptionProfile](ConsumptionProfile)


@pytest.mark.parametrize(
    "text",
    [
        '{"kind": "time_of_use", "used_kwh": {"peak": "1", "peak": "2"}}',
        '{"kind": "time_of_use", "used_kwh": {"peak": "1"}, "used_kwh": {"peak": "2"}}',
        '{"kind": "period_total", "kind": "period_total", "kwh": "1"}',
        '{"kind": "time_of_use", "used_kwh": {"peak": "1", "\\u0070eak": "2"}}',
        '{"kind": "time_of_use", "used_kwh": {"off_peak": "1"},'
        ' "exported_kwh": {"off_peak": "1", "off_peak": "2"}}',
    ],
)
def test_duplicate_json_keys_are_refused_at_any_depth(text: str) -> None:
    """JSON parsers (Pydantic's included) silently keep the last of two equal keys, so
    "peak" given twice would bill one of the two figures without a word (P4 note)."""
    PROFILE.validate_json(text)  # what the parser alone would accept
    with pytest.raises(DuplicateKeyError, match=r"^a key is given twice in one JSON object$"):
        parse_consumption_json(text)


def test_parse_consumption_json_validates_like_the_model() -> None:
    profile = parse_consumption_json('{"kind": "time_of_use", "used_kwh": {"peak": "1.5"}}')
    assert profile == TimeOfUseBuckets(used_kwh={TouPeriod.PEAK: Decimal("1.5")})
    with pytest.raises(ConsumptionJsonError):
        parse_consumption_json('{"kind": "time_of_use", "used_kwh": {"peak": 1.5}}')
    with pytest.raises(ConsumptionJsonError):
        parse_consumption_json("not json")


PLANTED = "John Smith 0821234567"


@pytest.mark.parametrize(
    "text",
    [
        f"not json {PLANTED}",
        f'{{"kind": "{PLANTED}"}}',
        '{"kind": "time_of_use", "used_kwh": {"peak": "-98765.4321"}}',
        f'{{"kind": "time_of_use", "used_kwh": {{"peak": "1"}}, "note": "{PLANTED}"}}',
        '{"kind": "period_total", "kwh": 98765.4321}',
        f'{{"kind": "time_of_use", "used_kwh": {{"{PLANTED}": "1"}}}}',  # a key, not a value
        f'{{"kind": "time_of_use", "used_kwh": {{"peak": "1"}}, "{PLANTED}": "1"}}',
    ],
)
def test_a_refusal_never_repeats_the_input(text: str) -> None:
    """Consumption figures and anything else a person sends stay out of messages (security
    register, input limits), including an unknown profile kind, which Pydantic would name."""
    with pytest.raises(ConsumptionJsonError) as caught:
        parse_consumption_json(text)
    shown = [str(caught.value), repr(caught.value.args), repr(caught.value.codes)]
    assert caught.value.__context__ is None  # no chain carries the original error
    assert caught.value.__cause__ is None
    for planted in ("98765", "0821234567", "John Smith"):
        assert all(planted not in text for text in shown)


def test_a_repeated_unvalidated_key_is_not_repeated_in_the_message() -> None:
    """Pydantic keeps the last of two equal keys, so an earlier value is never validated;
    its own keys still reach the duplicate check, and the message names none of them."""
    text = (
        f'{{"kind": "time_of_use", "used_kwh": {{"x": {{"{PLANTED}": 1, "{PLANTED}": 2}}}},'
        ' "used_kwh": {"peak": "2"}}'
    )
    with pytest.raises(DuplicateKeyError) as caught:
        parse_consumption_json(text)
    assert PLANTED not in str(caught.value)


def test_the_duplicate_check_is_linear() -> None:
    """32,000 repeats took 6.9 s with a quadratic check; this one stops at the first."""
    many = ", ".join(['"peak": "1"'] * 32_000)
    text = f'{{"kind": "time_of_use", "used_kwh": {{{many}}}}}'
    started = time.perf_counter()
    with pytest.raises(DuplicateKeyError):
        parse_consumption_json(text)
    assert time.perf_counter() - started < 2


def test_a_huge_number_in_an_unvalidated_value_is_a_fixed_refusal() -> None:
    """The earlier of two equal keys is never validated, so its value can hold what
    Pydantic's parser accepts but Python's refuses (or the other way round); either way the
    refusal is a `ConsumptionJsonError`, never a bare `ValueError` (P4-4 review)."""
    huge = "9" * 5000
    text = f'{{"kind": "time_of_use", "used_kwh": [{huge}], "used_kwh": {{"peak": "1"}}}}'
    with pytest.raises(ConsumptionJsonError) as caught:
        parse_consumption_json(text)
    assert huge[:20] not in str(caught.value)


def test_a_second_read_that_fails_is_a_fixed_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backstop when the second read fails for any reason a real input may not reach."""

    def refuse(*args: object, **kwargs: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", refuse)
    with pytest.raises(ConsumptionJsonError, match="could not be read a second time"):
        parse_consumption_json('{"kind": "period_total", "kwh": "1"}')


def test_a_refusal_carries_only_error_type_codes() -> None:
    with pytest.raises(ConsumptionJsonError) as caught:
        parse_consumption_json('{"kind": "time_of_use", "used_kwh": {"peak": "-1"}, "x": 1}')
    assert caught.value.codes
    assert all(code.isidentifier() for code in caught.value.codes)
    assert str(caught.value) == "the consumption input is not valid"


def test_an_unknown_kind_is_a_fixed_refusal() -> None:
    with pytest.raises(ConsumptionJsonError, match=r"^the consumption kind is not one"):
        parse_consumption_json('{"kind": "interval", "readings": []}')
