"""What the engine returns: line items that cite their sources by role, VAT, totals and
warnings."""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from munisense.domain.base import DomainModel
from munisense.domain.citations import Citation, StatusKind
from munisense.domain.money import ExactDecimal, Money, Rate, VatRate
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import VatTreatment


class QuantityUnit(StrEnum):
    KWH = "kWh"
    DAY = "day"
    MONTH = "month"


class SourceRole(StrEnum):
    """Which value of the tariff a citation backs on a line."""

    RATE = "rate"
    LOWER_THRESHOLD = "lower_threshold"
    UPPER_THRESHOLD = "upper_threshold"
    LABEL = "label"
    VAT_TREATMENT = "vat_treatment"
    FREE_ALLOWANCE = "free_allowance"
    SEASON = "season"
    SEASON_LABEL = "season_label"


class Source(DomainModel):
    """One cited value used on a line, and the role it played."""

    role: SourceRole
    citation: Citation
    status: StatusKind


class LineItem(DomainModel):
    """One charge or credit on the bill, with every value it used and their citations.

    A credit (the kWh made free by a free basic allocation) has a negative `amount`, equal to
    minus `rate` x `quantity`; its `quantity` and `rate` are positive."""

    component: str
    label: str
    description: str
    quantity: ExactDecimal
    unit: QuantityUnit
    rate: Rate
    amount: Money
    """Quantised at the policy's line-amount point, if it has one; exact otherwise."""
    vat_treatment: VatTreatment
    vat: Money | None
    """With VAT per line: this line's VAT (zero for zero-rated and exempt lines). With VAT
    on the subtotal: `None`, because VAT is not calculated per line."""
    sources: Annotated[tuple[Source, ...], Field(min_length=1)]
    status: StatusKind


class WarningCode(StrEnum):
    UNVERIFIED_VALUES = "unverified_values"
    UNVERIFIED_ROUNDING_POLICY = "unverified_rounding_policy"
    ASSUMED_FREE_BASIC_METHOD = "assumed_free_basic_method"
    UNVERIFIED_BILLING_POLICY = "unverified_billing_policy"
    TIME_OF_USE_SHARED_ACROSS_SEASONS = "time_of_use_shared_across_seasons"
    UNVERIFIED_EXPORT_CAP = "unverified_export_cap"


class BillWarning(DomainModel):
    code: WarningCode
    message: str


class Bill(DomainModel):
    """A forward calculation for one billing period under one tariff version."""

    supplier: str
    tariff_code: str
    tariff_name: str
    """The version's printed name."""
    version_effective_from: date
    version_effective_to: date | None
    period: DateRange
    consumption_kwh: ExactDecimal
    lines: tuple[LineItem, ...]
    subtotal: Money
    vat_rate: VatRate
    vat: Money
    total: Money
    status: StatusKind
    """The weakest status of every value the calculation relied on: each line's values,
    every header value of the version, and the VAT rate (percentage and dates). Values of
    components that produced no line (for example energy rates at zero consumption, or
    blocks not reached) do not count, because the bill does not depend on them."""
    rounding_policy: str
    rounding_policy_status: StatusKind
    free_basic_eligible: bool | None
    """The eligibility input as given (`None` when not given, for a tariff without a free
    basic allocation)."""
    month_fraction: ExactDecimal | None
    """For part of a calendar month priced by period splitting: the fraction of a month
    that every monthly value was scaled by (ADR-0011). `None` for a whole month."""
    warnings: tuple[BillWarning, ...]


class PeriodBill(DomainModel):
    """A billing period priced part by part (period splitting, ADR-0011). Each part is a
    `Bill` for one version, season, VAT rate and calendar month (or part of one); the
    period's subtotal, VAT and total are the sums of the parts'."""

    period: DateRange
    consumption_kwh: ExactDecimal
    parts: Annotated[tuple[Bill, ...], Field(min_length=1)]
    subtotal: Money
    vat: Money
    total: Money
    status: StatusKind
    """The weakest status of every part."""
    split: bool
    """True when the period was split into several parts or any part was pro-rated."""
    billing_policies: Annotated[tuple[str, ...], Field(min_length=1)]
    billing_policy_status: StatusKind
    rounding_policies: Annotated[tuple[str, ...], Field(min_length=1)]
    rounding_policy_status: StatusKind
    warnings: tuple[BillWarning, ...]


class MonthSoFar(DomainModel):
    """What a prepaid customer has bought earlier in the same calendar month (block reset:
    calendar month)."""

    purchases: Annotated[int, Field(ge=0)]
    kwh: Annotated[ExactDecimal, Field(ge=0)]


class PurchaseSegment(DomainModel):
    """The kWh bought between two block thresholds (of any component) of the month, at one
    price per kWh (every per-kWh rate in force there, with VAT where standard-rated)."""

    from_kwh: ExactDecimal
    to_kwh: ExactDecimal | None
    kwh: Annotated[ExactDecimal, Field(ge=0)]
    """In the last segment: what the rounded purchase leaves after the whole segments."""
    price_per_kwh: ExactDecimal
    """Rand per kWh, including VAT where the component is standard-rated."""
    amount: Money
    """The money spent in this segment, exact."""
    sources: Annotated[tuple[Source, ...], Field(min_length=1)]
    status: StatusKind


class Purchase(DomainModel):
    """A prepaid purchase: the money paid, what was deducted, and the kWh received."""

    day: date
    amount: Money
    """As paid, including VAT."""
    month_kwh_before: ExactDecimal
    fixed_charges: Money
    """Monthly fixed charges and levies deducted (with VAT), per the billing policy."""
    fixed_lines: tuple[LineItem, ...]
    energy_amount: Money
    segments: tuple[PurchaseSegment, ...]
    kwh: ExactDecimal
    """The kWh received, rounded once at the rounding policy's `prepaid_kwh` point."""
    month_kwh_after: ExactDecimal
    vat_rate: VatRate
    status: StatusKind
    rounding_policy: str
    rounding_policy_status: StatusKind
    billing_policy: str
    billing_policy_status: StatusKind
    warnings: tuple[BillWarning, ...]
