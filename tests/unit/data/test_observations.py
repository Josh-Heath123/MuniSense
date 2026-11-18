"""E39: the owner's prepaid purchases (unknown supplier) and the claims made about them.

Not tariff data. The test proves what `data/observations/README.md` says the figures show,
with exact fractions: kWh are printed to two decimals, so a purchase of `rand` giving `kwh`
constrains a flat price p to the interval where rand / p rounds to kwh.
"""

import json
from fractions import Fraction
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "data" / "observations"
FILE = PATH / "prepaid-purchases-unknown-supplier-2026.json"
CENT_KWH = Fraction(1, 100)


def purchases() -> list[tuple[Fraction, Fraction]]:
    data = json.loads(FILE.read_text(encoding="utf-8"))
    return [(Fraction(p["rand"]), Fraction(p["kwh"])) for p in data["purchases"]]


def price_range(rounding: str, deducted: Fraction = Fraction(0)) -> tuple[Fraction, Fraction]:
    """Prices p (rand per kWh, as paid) for which every purchase reproduces its kWh."""
    low_offset, high_offset = {
        "nearest": (CENT_KWH / 2, -CENT_KWH / 2),
        "down": (CENT_KWH, Fraction(0)),
        "up": (Fraction(0), -CENT_KWH),
    }[rounding]
    rows = purchases()
    low = max((rand - deducted) / (kwh + low_offset) for rand, kwh in rows)
    high = min((rand - deducted) / (kwh + high_offset) for rand, kwh in rows)
    return low, high


def test_the_file_holds_figures_only_for_an_unknown_supplier() -> None:
    data = json.loads(FILE.read_text(encoding="utf-8"))
    assert data["supplier"] is None
    assert data["tariff"] is None
    assert data["provided_by"] == "owner_prepaid_receipt"
    for purchase in data["purchases"]:
        assert set(purchase) == {"date", "order_in_day", "channel", "rand", "kwh"}


@pytest.mark.parametrize(
    ("rounding", "low", "high"),
    [
        ("nearest", "4.02972", "4.03022"),
        ("down", "4.02922", "4.02955"),
        ("up", "4.03023", "4.03063"),
    ],
)
def test_one_flat_price_fits_every_purchase(rounding: str, low: str, high: str) -> None:
    lowest, highest = price_range(rounding)
    assert lowest < highest
    # The README's ranges are the exact ones rounded inwards to five decimals.
    assert lowest <= Fraction(low) < Fraction(high) <= highest
    assert Fraction(low) - lowest < Fraction(1, 100000)
    assert highest - Fraction(high) < Fraction(1, 100000)


def test_the_owners_reading_of_about_4_030_fits() -> None:
    lowest, highest = price_range("nearest")
    assert lowest < Fraction("4.030") < highest


@pytest.mark.parametrize(
    ("rounding", "still_fits", "ruled_out"),
    [("nearest", "0.028", "0.03"), ("up", "0.048", "0.049"), ("down", "0.008", "0.009")],
)
def test_nothing_measurable_is_deducted_per_purchase(
    rounding: str, still_fits: str, ruled_out: str
) -> None:
    lowest, highest = price_range(rounding, deducted=Fraction(still_fits))
    assert lowest < highest  # a deduction this small cannot be ruled out
    lowest, highest = price_range(rounding, deducted=Fraction(ruled_out))
    assert lowest >= highest  # one this large is ruled out


def test_no_fixed_charge_was_taken_from_the_first_purchase_of_september() -> None:
    # Deduct only from the first purchase of the month (the R60.00 on 2026-09-10).
    def fits(deducted: Fraction) -> bool:
        rows = purchases()
        rows[0] = (rows[0][0] - deducted, rows[0][1])
        low = max(rand / (kwh + CENT_KWH / 2) for rand, kwh in rows)
        high = min(rand / (kwh - CENT_KWH / 2) for rand, kwh in rows)
        return low < high

    assert fits(Fraction("0.017"))  # up to about R0.0176 cannot be ruled out
    assert not fits(Fraction("0.018"))  # R0.018 or more is ruled out
