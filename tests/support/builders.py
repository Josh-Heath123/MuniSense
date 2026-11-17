"""Builders for fixture tariffs. Fixture values are invented and cite a fixture document.

Nothing here is real tariff data (CLAUDE.md rule 1). Tests that use real Ekurhuleni
figures build them from `tests/golden/` data with real citations instead.
"""

from datetime import date
from decimal import Decimal

from munisense.domain.citations import Citation, Cited, Estimated
from munisense.domain.money import ExactDecimal, Rate, RateUnit

FIXTURE_DOCUMENT = "f" * 64
FIXTURE_STATUS = Estimated(reason="test fixture; not real tariff data")


def fixture_citation(text: str = "fixture") -> Citation:
    return Citation(
        document_sha256=FIXTURE_DOCUMENT, page=1, locator="fixture table", printed_text=text
    )


def cited_decimal(value: str) -> Cited[ExactDecimal]:
    return Cited[ExactDecimal](
        value=Decimal(value), citation=fixture_citation(value), status=FIXTURE_STATUS
    )


def cited_rate(value: str, unit: RateUnit) -> Cited[Rate]:
    return Cited[Rate](
        value=Rate(value=Decimal(value), unit=unit),
        citation=fixture_citation(value),
        status=FIXTURE_STATUS,
    )


def cited_date(value: date) -> Cited[date]:
    return Cited[date](
        value=value, citation=fixture_citation(value.isoformat()), status=FIXTURE_STATUS
    )
