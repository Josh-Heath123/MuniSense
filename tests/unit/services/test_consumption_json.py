"""Reading consumption JSON with duplicate keys refused (P4-4). Values here are fixtures."""

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from munisense.domain.billing import ConsumptionProfile, TimeOfUseBuckets
from munisense.domain.tariffs import TouPeriod
from munisense.services.consumption import DuplicateKeyError, parse_consumption_json

PROFILE = TypeAdapter[ConsumptionProfile](ConsumptionProfile)


@pytest.mark.parametrize(
    "text",
    [
        '{"kind": "time_of_use", "used_kwh": {"peak": "1", "peak": "2"}}',
        '{"kind": "time_of_use", "used_kwh": {"peak": "1"}, "used_kwh": {"peak": "2"}}',
        '{"kind": "period_total", "kind": "period_total", "kwh": "1"}',
    ],
)
def test_duplicate_json_keys_are_refused_at_any_depth(text: str) -> None:
    """JSON parsers (Pydantic's included) silently keep the last of two equal keys, so
    "peak" given twice would bill one of the two figures without a word (P4 note)."""
    PROFILE.validate_json(text)  # what the parser alone would accept
    with pytest.raises(DuplicateKeyError, match="given twice"):
        parse_consumption_json(text)


def test_parse_consumption_json_validates_like_the_model() -> None:
    profile = parse_consumption_json('{"kind": "time_of_use", "used_kwh": {"peak": "1.5"}}')
    assert profile == TimeOfUseBuckets(used_kwh={TouPeriod.PEAK: Decimal("1.5")})
    with pytest.raises(ValidationError):
        parse_consumption_json('{"kind": "time_of_use", "used_kwh": {"peak": 1.5}}')
    with pytest.raises(ValidationError):
        parse_consumption_json("not json")
