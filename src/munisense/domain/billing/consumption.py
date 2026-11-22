"""Consumption input, designed as a profile type (ADR-0004, E3).

`ConsumptionProfile` is a discriminated union, so time-of-use and interval data can be
added without a redesign:

- `PeriodTotal`: the kWh used over the whole billing period (the roadmap's "monthly total";
  named for the period because periods are not always calendar months). Built in P1.
- `TimeOfUseBuckets`: kWh used and kWh exported per time-of-use period for the billing
  period (P4-4, ADR-0016 point 4). Accepted as input; the engine prices it from P4-7.

Interfaces read JSON input with `munisense.services.consumption.parse_consumption_json`,
which also refuses a key given twice: JSON parsers (Pydantic's included) silently keep the
last of two equal keys.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from munisense.domain.base import DomainModel
from munisense.domain.billing.errors import UnsupportedConsumptionError
from munisense.domain.money import ExactDecimal
from munisense.domain.tariffs.time_of_use import TouPeriod


def _no_negative_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


Kwh = Annotated[ExactDecimal, Field(ge=0), AfterValidator(_no_negative_zero)]


class PeriodTotal(DomainModel):
    """Total kWh used in the billing period."""

    kind: Literal["period_total"] = "period_total"
    kwh: Kwh


class TimeOfUseBuckets(DomainModel):
    """kWh used, and kWh exported, per time-of-use period over the billing period.

    At least one period must be used (a zero is fine); export is optional. At most one
    entry per period each, so at most three used and three exported. Whether the version's
    calendar defines each period is checked when the profile is priced (P4-7).
    """

    kind: Literal["time_of_use"] = "time_of_use"
    used_kwh: Annotated[dict[TouPeriod, Kwh], Field(min_length=1)]
    exported_kwh: dict[TouPeriod, Kwh] = Field(default_factory=dict)


ConsumptionProfile = Annotated[PeriodTotal | TimeOfUseBuckets, Field(discriminator="kind")]


def require_period_total(profile: PeriodTotal | TimeOfUseBuckets) -> PeriodTotal:
    """Return the profile if the engine can evaluate it; refuse anything else."""
    if isinstance(profile, PeriodTotal):
        return profile
    msg = "time-of-use consumption is not supported until time-of-use tariffs are built (P4)"
    raise UnsupportedConsumptionError(msg)
