"""What the engine returns: line items that cite their sources, VAT, totals and warnings."""

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


class LineItem(DomainModel):
    """One charge on the bill, with every value it used and their citations."""

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
    """VAT on this line when the policy applies VAT per line; otherwise `None`."""
    sources: Annotated[tuple[Citation, ...], Field(min_length=1)]
    status: StatusKind


class WarningCode(StrEnum):
    UNVERIFIED_VALUES = "unverified_values"
    UNVERIFIED_ROUNDING_POLICY = "unverified_rounding_policy"


class BillWarning(DomainModel):
    code: WarningCode
    message: str


class Bill(DomainModel):
    """A forward calculation for one billing period under one tariff version."""

    supplier: str
    tariff_code: str
    period: DateRange
    consumption_kwh: ExactDecimal
    lines: tuple[LineItem, ...]
    subtotal: Money
    vat_rate: VatRate
    vat: Money
    total: Money
    status: StatusKind
    """The weakest status of every value used: lines, the version header and the VAT rate."""
    rounding_policy: str
    rounding_policy_status: StatusKind
    warnings: tuple[BillWarning, ...]
