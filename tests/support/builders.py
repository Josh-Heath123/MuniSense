"""Builders for fixture tariffs. Fixture values are invented and cite a fixture document.

Nothing here is real tariff data (CLAUDE.md rule 1). Real Ekurhuleni figures, from P1-9,
are built with real citations to the committed source document instead. Production code
may never import this package (import-linter rule 6).
"""

from datetime import date
from decimal import Decimal

from munisense.domain.citations import Citation, Cited, Estimated, UserProvided, Verified
from munisense.domain.money import ExactDecimal, Rate, RateUnit
from munisense.domain.tariffs import PriceBasis, VatTreatment
from munisense.domain.tariffs.components import PrintedLabel

FIXTURE_DOCUMENT = "f" * 64
FIXTURE_STATUS = Estimated(reason="test fixture; not real tariff data")
type Status = Verified | Estimated | UserProvided


def fixture_citation(text: str = "fixture") -> Citation:
    return Citation(
        document_sha256=FIXTURE_DOCUMENT, page=1, locator="fixture table", printed_text=text
    )


def cited_decimal(value: str, status: Status = FIXTURE_STATUS) -> Cited[ExactDecimal]:
    return Cited[ExactDecimal](
        value=Decimal(value), citation=fixture_citation(value), status=status
    )


def cited_rate(value: str, unit: RateUnit, status: Status = FIXTURE_STATUS) -> Cited[Rate]:
    return Cited[Rate](
        value=Rate(value=Decimal(value), unit=unit),
        citation=fixture_citation(value),
        status=status,
    )


def cited_date(value: date, status: Status = FIXTURE_STATUS) -> Cited[date]:
    return Cited[date](value=value, citation=fixture_citation(value.isoformat()), status=status)


def cited_label(value: str, status: Status = FIXTURE_STATUS) -> Cited[PrintedLabel]:
    return Cited[PrintedLabel](value=value, citation=fixture_citation(value), status=status)


def cited_vat(
    value: VatTreatment = VatTreatment.STANDARD, status: Status = FIXTURE_STATUS
) -> Cited[VatTreatment]:
    return Cited[VatTreatment](value=value, citation=fixture_citation(), status=status)


def cited_basis(
    value: PriceBasis = PriceBasis.EXCLUDING_VAT, status: Status = FIXTURE_STATUS
) -> Cited[PriceBasis]:
    return Cited[PriceBasis](value=value, citation=fixture_citation(), status=status)
