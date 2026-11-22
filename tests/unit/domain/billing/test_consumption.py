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
from munisense.domain.tariffs import TouPeriod

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


def test_a_time_of_use_profile_gives_kwh_used_and_exported_per_period() -> None:
    profile = PROFILE.validate_json(
        '{"kind": "time_of_use", "used_kwh": {"peak": "100", "off_peak": "250.5"},'
        ' "exported_kwh": {"standard": "12"}}'
    )
    assert isinstance(profile, TimeOfUseBuckets)
    assert profile.used_kwh == {TouPeriod.PEAK: Decimal(100), TouPeriod.OFF_PEAK: Decimal("250.5")}
    assert profile.exported_kwh == {TouPeriod.STANDARD: Decimal(12)}


def test_export_is_optional_and_defaults_to_nothing() -> None:
    profile = TimeOfUseBuckets(used_kwh={TouPeriod.PEAK: Decimal(1)})
    assert profile.exported_kwh == {}


def test_a_time_of_use_profile_is_refused_by_the_engine_until_p4_7() -> None:
    profile = TimeOfUseBuckets(used_kwh={TouPeriod.PEAK: Decimal(1)})
    with pytest.raises(UnsupportedConsumptionError, match="time-of-use"):
        require_period_total(profile)


@pytest.mark.parametrize(
    "body",
    [
        '"used_kwh": {}',  # nothing used: at least one period
        '"used_kwh": {"peak": "-1"}',  # negative
        '"used_kwh": {"peak": "1"}, "exported_kwh": {"peak": "-0.5"}',
        '"used_kwh": {"Peak Hours!": "1"}',  # not a period name
        '"used_kwh": {"shoulder": "1"}',  # not one of Eskom's three periods (ADR-0016)
        '"used_kwh": {"peak": 1}',  # a number, not an exact decimal string
        '"used_kwh": {"peak": "1"}, "readings": []',  # an unknown field
        '"kwh_by_bucket": {"peak": "1"}',  # the P1 shape is gone
    ],
)
def test_an_invalid_time_of_use_profile_is_refused(body: str) -> None:
    with pytest.raises(ValidationError):
        PROFILE.validate_json(f'{{"kind": "time_of_use", {body}}}')


def test_the_limits_are_the_three_periods_used_and_exported() -> None:
    every = {period: Decimal(1) for period in TouPeriod}
    profile = TimeOfUseBuckets(used_kwh=every, exported_kwh=every)
    assert len(profile.used_kwh) == len(profile.exported_kwh) == len(TouPeriod) == 3


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
