"""Property tests for seasonal energy (P1-12).

- For random season calendars (1 to 6 seasons cutting the year at random days), every day
  of any year belongs to exactly the season an independent lookup predicts: the last
  season start on or before the day, wrapping to the last season before the first start.
- A span of days (up to 801 days) has a season exactly when every day in it has that
  season by the same lookup.
- A seasonal tariff whose seasons all have the same blocks bills exactly like the block
  tariff with those blocks, in every calendar month.
"""

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from munisense.domain.billing import BillingPeriod, PeriodTotal, calculate_bill
from munisense.domain.tariffs import SeasonalEnergy
from support.builders import (
    fixture_blocks,
    fixture_fixed,
    fixture_season,
    fixture_seasonal,
    fixture_vat_table,
    fixture_version,
)

LEAP = date(2028, 1, 1)
VAT = fixture_vat_table()

cut_days = st.lists(st.integers(0, 365), min_size=1, max_size=6, unique=True).map(sorted)


def _calendar(offsets: list[int]) -> tuple[SeasonalEnergy, list[tuple[int, int]]]:
    starts = [LEAP + timedelta(days=offset) for offset in offsets]
    seasons = []
    for index, start in enumerate(starts):
        end = starts[(index + 1) % len(starts)] - timedelta(days=1)
        seasons.append(
            fixture_season(
                f"s{index}", (start.month, start.day), (end.month, end.day), (None, "100")
            )
        )
    return fixture_seasonal(*seasons), [(s.month, s.day) for s in starts]


def _expected_index(starts: list[tuple[int, int]], day: date) -> int:
    position = bisect_right(starts, (day.month, day.day)) - 1
    return position if position >= 0 else len(starts) - 1  # before the first start: wraps


@given(cut_days, st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)))
def test_every_day_belongs_to_the_season_an_independent_lookup_predicts(
    offsets: list[int], day: date
) -> None:
    component, starts = _calendar(offsets)
    season = component.season_for(day, day)
    assert season is component.seasons[_expected_index(starts, day)]
    assert sum(s.dates.value.contains(day) for s in component.seasons) == 1


@given(
    cut_days,
    st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    st.integers(0, 800),
)
def test_a_span_has_a_season_only_when_every_day_shares_it(
    offsets: list[int], first: date, length: int
) -> None:
    component, starts = _calendar(offsets)
    last = first + timedelta(days=length)
    indexes = {
        _expected_index(starts, first + timedelta(days=offset)) for offset in range(length + 1)
    }
    found = component.season_for(first, last)
    if len(indexes) == 1:
        assert found is component.seasons[indexes.pop()]
    else:
        assert found is None


blocks = st.lists(st.integers(1, 2000), max_size=3, unique=True).map(sorted)
cents = st.integers(0, 100_000).map(lambda c: str(Decimal(c).scaleb(-2)))


@given(
    blocks,
    st.lists(cents, min_size=4, max_size=4),
    st.integers(0, 11),
    st.integers(0, 5_000_000).map(lambda k: Decimal(k).scaleb(-3)),
)
def test_equal_seasons_bill_like_the_block_tariff(
    bounds: list[int], rates: list[str], month_offset: int, used: Decimal
) -> None:
    pairs: list[tuple[str | None, str]] = [
        (str(bound), rate) for bound, rate in zip(bounds, rates, strict=False)
    ]
    pairs.append((None, rates[len(bounds)]))
    seasonal = fixture_seasonal(
        fixture_season("high", (6, 1), (8, 31), *pairs),
        fixture_season("low", (9, 1), (5, 31), *pairs),
    )
    start = date(2026 + (6 + month_offset) // 12, (6 + month_offset) % 12 + 1, 1)
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    period = BillingPeriod(start=start, end=end)
    basic = fixture_fixed("10.00")
    with_seasons = calculate_bill(
        fixture_version(basic, seasonal), period, PeriodTotal(kwh=used), VAT
    )
    with_blocks = calculate_bill(
        fixture_version(basic, fixture_blocks(*pairs)), period, PeriodTotal(kwh=used), VAT
    )
    assert [line.amount for line in with_seasons.lines] == [
        line.amount for line in with_blocks.lines
    ]
    assert with_seasons.total == with_blocks.total
