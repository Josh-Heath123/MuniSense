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
    InvalidPurchaseError,
    NonMonthlyPeriodError,
    PeriodCrossesSeasonError,
    PeriodOutsideVersionError,
    PrepaidNotSupportedError,
    PrepaidPrecisionError,
    PurchasesNotInOneMonthError,
    PurchaseTooSmallError,
    UnsupportedConsumptionError,
    UnsupportedPriceBasisError,
)
from munisense.domain.billing.prepaid import calculate_month, calculate_purchase
from munisense.domain.billing.result import (
    Bill,
    BillWarning,
    LineItem,
    MonthSoFar,
    PeriodBill,
    Purchase,
    PurchaseSegment,
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
    "InvalidPurchaseError",
    "LineItem",
    "MonthSoFar",
    "NonMonthlyPeriodError",
    "PeriodBill",
    "PeriodCrossesSeasonError",
    "PeriodOutsideVersionError",
    "PeriodTotal",
    "PrepaidNotSupportedError",
    "PrepaidPrecisionError",
    "Purchase",
    "PurchaseSegment",
    "PurchaseTooSmallError",
    "PurchasesNotInOneMonthError",
    "QuantityUnit",
    "Source",
    "SourceRole",
    "TimeOfUseBuckets",
    "UnsupportedConsumptionError",
    "UnsupportedPriceBasisError",
    "WarningCode",
    "calculate_bill",
    "calculate_month",
    "calculate_period",
    "calculate_purchase",
    "require_period_total",
]
