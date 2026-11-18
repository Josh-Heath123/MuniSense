# Observations

User-provided observations that are **not tariff data**. They are not cited to a tariff document, are not loaded as tariff versions and are not evidence about any named supplier.

## `prepaid-purchases-unknown-supplier-2026.json` (E39)

Four prepaid electricity purchases supplied by the owner on 2026-11-18, figures only (no meter number, token, name or address). The meter's **supplier and tariff are unknown**, and it is **not** an Ekurhuleni meter (E34). `provided_by` reuses the `owner_prepaid_receipt` source category of tariff provenance; the figures came from the owner's bank-app purchase history. The figures can be linked to the owner (see the security and privacy register).

| Date | Order that day | Channel | Rand paid | kWh received |
| --- | --- | --- | --- | --- |
| 2026-09-10 | 1 | bank app | 60.00 | 14.89 |
| 2026-09-10 | 2 | bank app | 160.00 | 39.70 |
| 2026-10-18 | 1 | bank app | 200.00 | 49.63 |
| 2026-11-15 | 1 | bank app | 200.00 | 49.63 |

### What the figures show (checked by `tests/unit/data/test_observations.py`)

- **One flat price fits all four**, whichever way the kWh are rounded to two decimals:

  | kWh rounding | Price range that reproduces every purchase (R/kWh, as paid) |
  | --- | --- |
  | to nearest | 4.02972 to 4.03022 |
  | down | 4.02922 to 4.02955 |
  | up | 4.03023 to 4.03063 |

  The owner's reading, "about R4.030/kWh including VAT", lies in the "to nearest" range. Whether the amount paid includes VAT is the owner's reading; the figures alone cannot show it.
- **Nothing is deducted per purchase**, to within the precision of the figures: with a fixed amount deducted from every purchase, one flat price still fits only if that amount is at most about R0.03 when kWh are rounded to nearest (about R0.05 if rounded up, R0.008 if rounded down).
- **No fixed charge was taken from the first purchase of September**, to within about R0.02 (under R0.018 when kWh are rounded to nearest): the R60.00 purchase gives the same price as the others. Whether one is recovered some other way (for example billed separately) cannot be seen from purchases.

### Uses

- Shape and precision of real prepaid purchases (two-decimal kWh), as test inputs for the prepaid calculation (P1-14), with no claim about any tariff.
- A reminder that the `BillingPolicy` must allow prepaid fixed charges to be recovered in different ways, including not from purchases at all (E38).
