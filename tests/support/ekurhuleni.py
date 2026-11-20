"""The P1-9 hand-checked Tariff B bills (prices from the drafts; see the P1-9 test module).

Shared by the file test (`tests/unit/data/test_ekurhuleni_2026_27.py`) and the database
round trip (`tests/integration/persistence/test_repository.py`), so both check the same cents.
Each case: phase, billing month, kWh, line amounts, subtotal, VAT, total.
"""

from datetime import date

from munisense.domain.billing import BillingPeriod


def month(year: int, number: int) -> BillingPeriod:
    end = date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1)
    return BillingPeriod(start=date(year, number, 1), end=end)


BILL_CASES = [
    # July 2026 (high-demand season), nothing used:
    #   basic 109.78; subtotal 109.78; VAT 15% = 16.467 -> 16.47; total 126.25
    ("1-phase", month(2026, 7), "0", ["109.78"], "109.78", "16.47", "126.25"),
    # July 2026, 350 kWh:
    #   energy 350 x 3.3700 = 1179.50; subtotal 109.78 + 1179.50 = 1289.28
    #   VAT 15% = 193.392 -> 193.39; total 1482.67
    ("1-phase", month(2026, 7), "350", ["109.78", "1179.50"], "1289.28", "193.39", "1482.67"),
    # February 2027 (low-demand season, 28 days; the basic charge is per month):
    #   energy 123.45 x 3.3700 = 416.0265 -> 416.03; subtotal 525.81
    #   VAT 15% = 78.8715 -> 78.87; total 604.68
    ("1-phase", month(2027, 2), "123.45", ["109.78", "416.03"], "525.81", "78.87", "604.68"),
    # January 2027 (low-demand season), 3-phase, 812.4 kWh:
    #   basic 203.89; energy 812.4 x 3.3700 = 2737.788 -> 2737.79; subtotal 2941.68
    #   VAT 15% = 441.252 -> 441.25; total 3382.93
    ("3-phase", month(2027, 1), "812.4", ["203.89", "2737.79"], "2941.68", "441.25", "3382.93"),
    # June 2027 (high-demand season, last month of the version), 50.5 kWh; the energy
    # line is an exact half (half-even would give 170.18); VAT is not a tie:
    #   energy 50.5 x 3.3700 = 170.185 -> 170.19; subtotal 279.97
    #   VAT 15% = 41.9955 -> 42.00; total 321.97
    ("1-phase", month(2027, 6), "50.5", ["109.78", "170.19"], "279.97", "42.00", "321.97"),
    # October 2026 (low-demand season), 101.4 kWh; VAT is an exact half with an even
    # cent digit, so half up and half even differ (half even would give 67.72):
    #   energy 101.4 x 3.3700 = 341.718 -> 341.72; subtotal 109.78 + 341.72 = 451.50
    #   VAT 15% = 67.725 -> 67.73; total 519.23
    ("1-phase", month(2026, 10), "101.4", ["109.78", "341.72"], "451.50", "67.73", "519.23"),
]
