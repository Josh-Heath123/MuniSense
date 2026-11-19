"""The supplier catalogue: `data/catalogue/suppliers.json` (P2-6, ADR-0012 section 2)."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from munisense.domain.base import DomainModel
from munisense.domain.citations import Cited
from munisense.domain.citations.model import Text
from munisense.domain.tariffs.version import Code


class SupplierKind(StrEnum):
    MUNICIPALITY = "municipality"
    MUNICIPAL_UTILITY = "municipal_utility"
    ESKOM = "eskom"


Month = Annotated[int, Field(ge=1, le=12)]


class Supplier(DomainModel):
    """One body that bills customers for electricity.

    `tariff_year_start_month` is tariff data (when a year of tariffs starts), so it is cited
    like any other value (CLAUDE.md rule 1).
    """

    code: Code
    name: Text
    kind: SupplierKind
    tariff_year_start_month: Cited[Month]

    def tariff_year(self, day: date) -> str:
        """The drafts folder name for the tariff year containing `day`.

        `2026-27` for a year starting in any month but January; `2026` for a calendar year
        (P2-8; ADR-0012 section 2 names the folder `<tariff-year>`).
        """
        first_month = self.tariff_year_start_month.value
        first_year = day.year if day.month >= first_month else day.year - 1
        if first_month == 1:
            return str(first_year)
        return f"{first_year}-{(first_year + 1) % 100:02d}"


class SupplierCatalogue(DomainModel):
    schema_version: int = Field(ge=1, le=1)
    suppliers: Annotated[tuple[Supplier, ...], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def _unique_codes(self) -> Self:
        codes = [s.code for s in self.suppliers]
        if len(set(codes)) != len(codes):
            msg = "supplier codes must be unique"
            raise ValueError(msg)
        if codes != sorted(codes):
            msg = "suppliers must be listed in code order"
            raise ValueError(msg)
        return self

    def by_code(self, code: str) -> Supplier:
        for supplier in self.suppliers:
            if supplier.code == code:
                return supplier
        msg = f"no supplier {code!r} in the catalogue"
        raise KeyError(msg)
