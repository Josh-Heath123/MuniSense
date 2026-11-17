"""Consumption profiles and the billing period (P1-5). Values here are fixtures."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from munisense.domain.billing import (
    BillingPeriod,
    ConsumptionProfile,
    PeriodTotal,
    TimeOfUseBuckets,
    UnsupportedConsumptionError,
    require_period_total,
)

PROFILE = TypeAdapter[ConsumptionProfile](ConsumptionProfile)


def test_a_period_total_is_kwh_for_the_whole_billing_period() -> None:
    total = PeriodTotal(kwh=Decimal("523.4"))
    assert require_period_total(total).kwh == Decimal("523.4")


@pytest.mark.parametrize("kwh", ["-0.1", "-1"])
def test_negative_consumption_is_refused(kwh: str) -> None:
    with pytest.raises(ValidationError):
        PeriodTotal(kwh=Decimal(kwh))


def test_zero_consumption_is_allowed() -> None:
    assert PeriodTotal(kwh=Decimal("0")).kwh == 0


def test_consumption_refuses_floats() -> None:
    with pytest.raises(ValidationError):
        PROFILE.validate_json('{"kind": "period_total", "kwh": 523.4}')


def test_a_profile_is_read_from_json_by_its_kind() -> None:
    profile = PROFILE.validate_json('{"kind": "period_total", "kwh": "523.4"}')
    assert isinstance(profile, PeriodTotal)


def test_a_time_of_use_profile_can_be_described_but_is_refused_until_p4() -> None:
    profile = PROFILE.validate_json(
        '{"kind": "time_of_use", "kwh_by_bucket": {"peak": "100", "off_peak": "250.5"}}'
    )
    assert isinstance(profile, TimeOfUseBuckets)
    with pytest.raises(UnsupportedConsumptionError, match="time-of-use"):
        require_period_total(profile)


@pytest.mark.parametrize(
    "buckets",
    [
        "{}",
        '{"peak": "-1"}',
        '{"Peak Hours!": "1"}',
        "{" + ", ".join(f'"b{i}": "1"' for i in range(25)) + "}",
    ],
)
def test_an_invalid_time_of_use_profile_is_refused(buckets: str) -> None:
    with pytest.raises(ValidationError):
        PROFILE.validate_json(f'{{"kind": "time_of_use", "kwh_by_bucket": {buckets}}}')


def test_the_bucket_limits_are_inclusive() -> None:
    buckets = ", ".join(f'"b{i}": "1"' for i in range(24))
    profile = PROFILE.validate_json(f'{{"kind": "time_of_use", "kwh_by_bucket": {{{buckets}}}}}')
    assert isinstance(profile, TimeOfUseBuckets)
    assert len(profile.kwh_by_bucket) == 24
    longest = "a" * 32
    assert longest in TimeOfUseBuckets(kwh_by_bucket={longest: Decimal("1")}).kwh_by_bucket
    with pytest.raises(ValidationError):
        TimeOfUseBuckets(kwh_by_bucket={"a" * 33: Decimal("1")})


def test_negative_zero_kwh_becomes_zero() -> None:
    assert not PeriodTotal(kwh=Decimal("-0")).kwh.is_signed()


def test_an_unknown_profile_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        PROFILE.validate_json('{"kind": "interval", "readings": []}')


def test_a_billing_period_is_a_half_open_date_range() -> None:
    period = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
    assert period.days == 31
    assert not period.contains(date(2026, 8, 1))


def test_an_empty_billing_period_is_refused() -> None:
    with pytest.raises(ValidationError):
        BillingPeriod(start=date(2026, 7, 1), end=date(2026, 7, 1))
