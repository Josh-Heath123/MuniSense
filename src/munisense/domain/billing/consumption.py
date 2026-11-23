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

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator
from pydantic_core import PydanticCustomError

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


# Interval readings (P4-10, ADR-0016 point 4).
MAX_INTERVALS = 44_640  # a 31-day month of 1-minute readings
SAST = timedelta(hours=2)  # South African Standard Time, UTC+02:00, no daylight saving


class IntervalReading(DomainModel):
    """The kWh used, and exported, in one interval starting at `start` (SAST, +02:00)."""

    start: AwareDatetime
    used_kwh: Kwh
    exported_kwh: Kwh = Decimal(0)


class IntervalReadings(DomainModel):
    """kWh per interval of one fixed length that divides an hour, one after another with
    no gap or overlap, each starting on the interval grid in South African Standard Time.

    The readings show when people are at home: they are calculation inputs only, never
    stored or logged, and a refusal names at most the interval's position, never a time
    or a kWh figure (ADR-0016 point 4)."""

    kind: Literal["intervals"] = "intervals"
    minutes: Literal[1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]
    readings: Annotated[tuple[IntervalReading, ...], Field(min_length=1, max_length=MAX_INTERVALS)]

    @model_validator(mode="after")
    def _a_grid_without_gaps(self) -> Self:
        step = timedelta(minutes=self.minutes)
        previous: datetime | None = None
        for index, reading in enumerate(self.readings):
            start = reading.start
            # Each refusal has its own error type (a fixed code) and names only the
            # interval's position (in `ctx`), never a time or a kWh figure.
            if start.utcoffset() != SAST:
                raise PydanticCustomError(
                    "interval_not_sast",
                    "interval {index}: its start is not in South African Standard Time (+02:00)",
                    {"index": index},
                )
            if start.second or start.microsecond or (start.hour * 60 + start.minute) % self.minutes:
                raise PydanticCustomError(
                    "interval_off_grid",
                    "interval {index}: it does not start on the interval grid",
                    {"index": index},
                )
            if previous is not None and start > previous + step:
                raise PydanticCustomError(
                    "interval_gap", "interval {index}: a gap before it", {"index": index}
                )
            if previous is not None and start < previous + step:
                raise PydanticCustomError(
                    "interval_overlap",
                    "interval {index}: it overlaps the one before",
                    {"index": index},
                )
            previous = start
        return self

    @property
    def first_start(self) -> datetime:
        return self.readings[0].start

    @property
    def end(self) -> datetime:
        return self.readings[-1].start + timedelta(minutes=self.minutes)


type Consumption = PeriodTotal | TimeOfUseBuckets | IntervalReadings
ConsumptionProfile = Annotated[
    PeriodTotal | TimeOfUseBuckets | IntervalReadings, Field(discriminator="kind")
]


def require_period_total(profile: Consumption) -> PeriodTotal:
    """Return the profile if the engine can evaluate it; refuse anything else."""
    if isinstance(profile, PeriodTotal):
        return profile
    msg = "time-of-use consumption is not supported until time-of-use tariffs are built (P4)"
    raise UnsupportedConsumptionError(msg)
