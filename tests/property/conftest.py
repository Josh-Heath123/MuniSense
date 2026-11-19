"""The slowest property tests are `slow` (E43), so `uv run poe check` stays under 25 s on
the owner's machine. `uv run poe verify` and CI still run every property test.

Chosen by measured duration (`pytest --durations`): every property test taking 0.29 s or
more on 2026-11-18, and 0.19 s or more on 2026-11-19; the faster ones stay in `poe check`.
"""

import pytest
from hypothesis import settings

# No per-example deadline: on a loaded machine (the owner's WSL disk, a slow CI runner) a
# 200 ms deadline fails for timing, not correctness. One full run on 2026-11-19 failed
# intermittently while taking 191 s instead of the usual 35-70 s; the test was not captured.
settings.register_profile("munisense", deadline=None)
settings.load_profile("munisense")

SLOWEST = {
    "test_parts_tile_the_period_and_share_the_kwh_exactly",  # 0.49 s
    "test_amounts_and_vat_match_an_independent_calculation",  # 0.38 s
    "test_block_quantities_add_up_and_stay_inside_their_blocks",  # 0.38 s
    "test_a_bill_is_never_negative",  # 0.34 s
    "test_equal_seasons_bill_like_the_block_tariff",  # 0.32 s
    "test_a_month_of_purchases_costs_what_the_month_is_billed",  # 0.31 s
    "test_a_block_bill_never_falls_as_consumption_rises",  # 0.31 s
    "test_splitting_a_month_changes_the_total_by_no_more_than_rounding",  # 0.29 s
    # Added in P2-3 (2026-11-19), when `poe check` measured 26-33 s again:
    "test_more_money_never_buys_fewer_kwh",  # 0.28 s
    "test_the_kwh_received_cost_what_was_paid_within_the_rounding",  # 0.27 s
    "test_extreme_values_end_in_a_bill_or_a_domain_error",  # 0.24 s
    "test_every_day_belongs_to_the_season_an_independent_lookup_predicts",  # 0.19 s
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if isinstance(item, pytest.Function) and item.originalname in SLOWEST:
            item.add_marker(pytest.mark.slow)
