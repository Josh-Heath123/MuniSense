"""Half-open date ranges (P1-4). Dates are passed in; nothing reads the clock."""

from datetime import date

import pytest
from pydantic import ValidationError

from munisense.domain.periods import DateRange

JULY = DateRange(start=date(2026, 7, 1), end=date(2026, 8, 1))


def test_a_range_is_half_open() -> None:
    assert JULY.contains(date(2026, 7, 1))
    assert JULY.contains(date(2026, 7, 31))
    assert not JULY.contains(date(2026, 8, 1))
    assert JULY.days == 31


@pytest.mark.parametrize(
    ("start", "end"),
    [(date(2026, 7, 1), date(2026, 7, 1)), (date(2026, 8, 1), date(2026, 7, 1))],
)
def test_an_empty_or_reversed_range_is_refused(start: date, end: date) -> None:
    with pytest.raises(ValidationError):
        DateRange(start=start, end=end)


def test_covers_and_overlaps() -> None:
    first_half = DateRange(start=date(2026, 7, 1), end=date(2026, 7, 16))
    straddling = DateRange(start=date(2026, 7, 20), end=date(2026, 8, 10))
    august = DateRange(start=date(2026, 8, 1), end=date(2026, 9, 1))
    assert JULY.covers(first_half)
    assert JULY.covers(JULY)
    assert not JULY.covers(straddling)
    assert JULY.overlaps(straddling)
    assert not JULY.overlaps(august)  # adjacent, not overlapping


def test_whole_calendar_month() -> None:
    assert JULY.is_whole_calendar_month
    assert not DateRange(start=date(2026, 7, 2), end=date(2026, 8, 2)).is_whole_calendar_month
    assert not DateRange(start=date(2026, 7, 1), end=date(2026, 9, 1)).is_whole_calendar_month
    december = DateRange(start=date(2026, 12, 1), end=date(2027, 1, 1))
    assert december.is_whole_calendar_month


def test_json_round_trip() -> None:
    assert DateRange.model_validate_json(JULY.model_dump_json()) == JULY
