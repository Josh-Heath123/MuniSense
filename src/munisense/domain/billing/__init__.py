"""Bill and prepaid purchase calculation, period splitting, line items and warnings."""

from munisense.domain.billing.consumption import (
    ConsumptionProfile,
    PeriodTotal,
    TimeOfUseBuckets,
    require_period_total,
)
from munisense.domain.billing.engine import calculate_bill
from munisense.domain.billing.errors import (
    FreeBasicEligibilityRequiredError,
    FreeBasicNotOfferedError,
    NonMonthlyPeriodError,
    PeriodOutsideVersionError,
    UnsupportedConsumptionError,
    UnsupportedPriceBasisError,
)
from munisense.domain.billing.result import (
    Bill,
    BillWarning,
    LineItem,
    QuantityUnit,
    Source,
    SourceRole,
    WarningCode,
)
from munisense.domain.periods import DateRange as BillingPeriod

__all__ = [
    "Bill",
    "BillWarning",
    "BillingPeriod",
    "ConsumptionProfile",
    "FreeBasicEligibilityRequiredError",
    "FreeBasicNotOfferedError",
    "LineItem",
    "NonMonthlyPeriodError",
    "PeriodOutsideVersionError",
    "PeriodTotal",
    "QuantityUnit",
    "Source",
    "SourceRole",
    "TimeOfUseBuckets",
    "UnsupportedConsumptionError",
    "UnsupportedPriceBasisError",
    "WarningCode",
    "calculate_bill",
    "require_period_total",
]
