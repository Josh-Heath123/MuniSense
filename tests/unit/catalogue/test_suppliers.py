"""The supplier catalogue model (P2-6)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from munisense.catalogue.suppliers import SupplierCatalogue

ROOT = Path(__file__).resolve().parents[3]
BODY: dict[str, Any] = json.loads((ROOT / "data/catalogue/suppliers.json").read_text("utf-8"))


def _with(suppliers: list[dict[str, Any]]) -> str:
    return json.dumps({**BODY, "suppliers": suppliers})


def test_the_committed_catalogue_loads() -> None:
    catalogue = SupplierCatalogue.model_validate_json(json.dumps(BODY))
    assert catalogue.by_code("city-of-ekurhuleni").tariff_year_start_month.value == 7


def test_duplicate_codes_are_refused() -> None:
    supplier = BODY["suppliers"][0]
    with pytest.raises(ValidationError, match="supplier codes must be unique"):
        SupplierCatalogue.model_validate_json(_with([supplier, supplier]))


def test_suppliers_must_be_in_code_order() -> None:
    first = BODY["suppliers"][0]
    other = {**first, "code": "a-first-code"}
    with pytest.raises(ValidationError, match="code order"):
        SupplierCatalogue.model_validate_json(_with([first, other]))


@pytest.mark.parametrize("month", [0, 13])
def test_a_start_month_outside_the_year_is_refused(month: int) -> None:
    supplier = json.loads(json.dumps(BODY["suppliers"][0]))
    supplier["tariff_year_start_month"]["value"] = month
    with pytest.raises(ValidationError, match="tariff_year_start_month"):
        SupplierCatalogue.model_validate_json(_with([supplier]))
