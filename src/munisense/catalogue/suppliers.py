"""The supplier catalogue: `data/catalogue/suppliers.json` (P2-6, ADR-0012 section 2)."""

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
