"""The dated VAT table (P1-4, ADR-0005). Rates here are fixtures, not the real VAT rate."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.citations import Citation, Cited, Estimated
from munisense.domain.money import (
    ExactDecimal,
    NoVatRateError,
    VatRate,
    VatRateChangesError,
    VatTable,
)
from munisense.domain.periods import DateRange

FIXTURE_CITATION = Citation(
    document_sha256="b" * 64, page=1, locator="fixture", printed_text="fixture"
)
FIXTURE_STATUS = Estimated(reason="test fixture, not the real VAT rate")


def vat(percent: str, start: date, end: date | None) -> VatRate:
    return VatRate(
        start=start,
        end=end,
        percent=Cited[ExactDecimal](
            value=Decimal(percent), citation=FIXTURE_CITATION, status=FIXTURE_STATUS
        ),
    )


OLD = vat("10", date(2020, 1, 1), date(2026, 3, 1))
NEW = vat("12.5", date(2026, 3, 1), None)
TABLE = VatTable(rates=(OLD, NEW))


def test_the_rate_for_a_period_inside_one_entry() -> None:
    july = DateRange(start=date(2026, 7, 1), end=date(2026, 8, 1))
    assert TABLE.rate_for(july) is NEW
    assert NEW.fraction == Decimal("0.125")


def test_a_period_before_the_table_is_refused() -> None:
    with pytest.raises(NoVatRateError):
        TABLE.rate_for(DateRange(start=date(2019, 12, 1), end=date(2020, 1, 1)))


def test_a_period_partly_before_the_table_is_refused() -> None:
    with pytest.raises(NoVatRateError):
        TABLE.rate_for(DateRange(start=date(2019, 12, 15), end=date(2020, 1, 15)))


def test_a_period_across_a_rate_change_is_refused() -> None:
    # Splitting a period at a VAT change is P1-13's job; until then, refuse.
    with pytest.raises(VatRateChangesError):
        TABLE.rate_for(DateRange(start=date(2026, 2, 15), end=date(2026, 3, 15)))


def test_a_period_after_a_closed_last_entry_is_refused() -> None:
    table = VatTable(rates=(OLD,))
    with pytest.raises(NoVatRateError):
        table.rate_for(DateRange(start=date(2026, 3, 1), end=date(2026, 4, 1)))


def test_an_empty_table_is_refused() -> None:
    with pytest.raises(ValidationError):
        VatTable(rates=())


@pytest.mark.parametrize(
    "rates",
    [
        (vat("10", date(2020, 1, 1), date(2026, 4, 1)), NEW),  # overlap
        (vat("10", date(2020, 1, 1), date(2026, 2, 1)), NEW),  # gap
        (NEW, OLD),  # out of order
        (vat("10", date(2020, 1, 1), None), NEW),  # an open entry before another
    ],
)
def test_overlapping_gapped_or_unordered_entries_are_refused(rates: tuple[VatRate, ...]) -> None:
    with pytest.raises(ValidationError):
        VatTable(rates=rates)


@pytest.mark.parametrize("percent", ["-1", "100.01"])
def test_an_impossible_percentage_is_refused(percent: str) -> None:
    with pytest.raises(ValidationError):
        vat(percent, date(2020, 1, 1), None)


def test_an_entry_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValidationError):
        vat("10", date(2026, 3, 1), date(2026, 3, 1))


def test_the_table_round_trips_through_json() -> None:
    assert VatTable.model_validate_json(TABLE.model_dump_json()) == TABLE
