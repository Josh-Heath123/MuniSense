"""The slowest property tests are `slow` (E43), so `uv run poe check` stays under 25 s on
the owner's machine. `uv run poe verify` and CI still run every property test.

Chosen by measured duration (`pytest --durations`, 2026-11-18): every property test taking
0.29 s or more; the faster ones stay in `poe check`.
"""

import pytest

SLOWEST = {
    "test_parts_tile_the_period_and_share_the_kwh_exactly",  # 0.49 s
    "test_amounts_and_vat_match_an_independent_calculation",  # 0.38 s
    "test_block_quantities_add_up_and_stay_inside_their_blocks",  # 0.38 s
    "test_a_bill_is_never_negative",  # 0.34 s
    "test_equal_seasons_bill_like_the_block_tariff",  # 0.32 s
    "test_a_month_of_purchases_costs_what_the_month_is_billed",  # 0.31 s
    "test_a_block_bill_never_falls_as_consumption_rises",  # 0.31 s
    "test_splitting_a_month_changes_the_total_by_no_more_than_rounding",  # 0.29 s
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if isinstance(item, pytest.Function) and item.originalname in SLOWEST:
            item.add_marker(pytest.mark.slow)
