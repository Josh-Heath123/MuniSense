"""Consumption input, designed as a profile type (ADR-0004, E3).

`ConsumptionProfile` is a discriminated union, so time-of-use and interval data can be
added without a redesign:

- `PeriodTotal`: the kWh used over the whole billing period (the roadmap's "monthly total";
  named for the period because periods are not always calendar months). Built in P1.
- `TimeOfUseBuckets`: kWh per time-of-use bucket. Accepted as input so the shape is fixed
  now, but refused by the engine until time-of-use is built in P4.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints

from munisense.domain.base import DomainModel
from munisense.domain.billing.errors import UnsupportedConsumptionError
from munisense.domain.money import ExactDecimal


def _no_negative_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


Kwh = Annotated[ExactDecimal, Field(ge=0), AfterValidator(_no_negative_zero)]
BucketName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]


class PeriodTotal(DomainModel):
    """Total kWh used in the billing period."""

    kind: Literal["period_total"] = "period_total"
    kwh: Kwh


class TimeOfUseBuckets(DomainModel):
    """kWh per time-of-use bucket (for example peak, standard, off_peak). Evaluated from P4."""

    kind: Literal["time_of_use"] = "time_of_use"
    kwh_by_bucket: Annotated[dict[BucketName, Kwh], Field(min_length=1, max_length=24)]


ConsumptionProfile = Annotated[PeriodTotal | TimeOfUseBuckets, Field(discriminator="kind")]


def require_period_total(profile: PeriodTotal | TimeOfUseBuckets) -> PeriodTotal:
    """Return the profile if the engine can evaluate it; refuse anything else."""
    if isinstance(profile, PeriodTotal):
        return profile
    msg = "time-of-use consumption is not supported until time-of-use tariffs are built (P4)"
    raise UnsupportedConsumptionError(msg)
