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
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.billing.errors import UnsupportedConsumptionError
from munisense.domain.money import ExactDecimal
from munisense.domain.tariffs.components import Quantity
from munisense.domain.tariffs.tou_period import TouPeriod


def _no_negative_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


Kwh = Annotated[ExactDecimal, Field(ge=0), AfterValidator(_no_negative_zero)]
Kva = Kwh  # the same rules: exact, never negative, no negative zero


class PeriodTotal(DomainModel):
    """Total kWh used in the billing period."""

    kind: Literal["period_total"] = "period_total"
    kwh: Kwh


class TimeOfUseBuckets(DomainModel):
    """kWh used, and kWh exported, per time-of-use period over the billing period.

    At most one entry per period each, so at most three used and three exported.

    An absent period is never read as zero use: when the profile is priced (P4-7), every
    period the version's calendar defines must be in `used_kwh` (a zero is given as "0"),
    and a period the calendar does not define is refused. Export is optional, because not
    every customer exports; a period absent from `exported_kwh` exported nothing. A period
    may be exported only if it is also given as used, because the export credit is capped
    by the kWh used in the same period (ADR-0016 point 6).
    """

    kind: Literal["time_of_use"] = "time_of_use"
    used_kwh: Annotated[dict[TouPeriod, Kwh], Field(min_length=1)]
    exported_kwh: dict[TouPeriod, Kwh] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exported_only_where_used(self) -> Self:
        if not self.exported_kwh.keys() <= self.used_kwh.keys():
            msg = "a period is exported but not given as used (give its use, even 0)"
            raise ValueError(msg)
        return self


class CustomerQuantities(DomainModel):
    """The customer's quantities for one billing month, in kVA, that quantity charges are
    priced on (P4-9). Each is optional, exact, never negative (a negative zero becomes
    zero); unknown names are refused, and nothing here is ever stored or logged."""

    measured_maximum_demand_kva: Kva | None = None
    notified_maximum_demand_kva: Kva | None = None
    annual_utilised_capacity_kva: Kva | None = None

    def given(self) -> dict[Quantity, Decimal]:
        """The quantities given, by name."""
        values = {q: getattr(self, q.value) for q in Quantity}
        return {q: v for q, v in values.items() if v is not None}


ConsumptionProfile = Annotated[PeriodTotal | TimeOfUseBuckets, Field(discriminator="kind")]


def require_period_total(profile: PeriodTotal | TimeOfUseBuckets) -> PeriodTotal:
    """Return the profile if the engine can evaluate it; refuse anything else."""
    if isinstance(profile, PeriodTotal):
        return profile
    msg = "time-of-use consumption is not supported until time-of-use tariffs are built (P4)"
    raise UnsupportedConsumptionError(msg)
