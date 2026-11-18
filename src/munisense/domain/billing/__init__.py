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
    IncompatibleVersionsError,
    NonMonthlyPeriodError,
    PeriodCrossesSeasonError,
    PeriodOutsideVersionError,
    UnsupportedConsumptionError,
    UnsupportedPriceBasisError,
)
from munisense.domain.billing.result import (
    Bill,
    BillWarning,
    LineItem,
    PeriodBill,
    QuantityUnit,
    Source,
    SourceRole,
    WarningCode,
)
from munisense.domain.billing.splitting import calculate_period
from munisense.domain.periods import DateRange as BillingPeriod

__all__ = [
    "Bill",
    "BillWarning",
    "BillingPeriod",
    "ConsumptionProfile",
    "FreeBasicEligibilityRequiredError",
    "FreeBasicNotOfferedError",
    "IncompatibleVersionsError",
    "LineItem",
    "NonMonthlyPeriodError",
    "PeriodBill",
    "PeriodCrossesSeasonError",
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
    "calculate_period",
    "require_period_total",
]
