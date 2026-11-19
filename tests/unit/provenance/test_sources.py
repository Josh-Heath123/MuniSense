"""Source-document manifests and the draft reader and writer (P2-6)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from munisense.domain.money import VatRate
from munisense.provenance.canonical import CanonicalJsonError
from munisense.provenance.drafts import load_file, write_file
from munisense.provenance.sources import SourceManifest

ROOT = Path(__file__).resolve().parents[3]
SARS: dict[str, Any] = json.loads((ROOT / "data/sources/sars/sources.json").read_text("utf-8"))


@pytest.mark.parametrize("field", ["sha256", "file"])
def test_a_manifest_refuses_a_document_listed_twice(field: str) -> None:
    first, second = SARS["documents"]
    clash = {**second, field: first[field]}
    with pytest.raises(ValidationError, match=f"each document's {field} must be unique"):
        SourceManifest.model_validate_json(json.dumps({**SARS, "documents": [first, clash]}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url", "http://www.sars.gov.za/x.pdf"),
        ("file", "Guide.PDF"),
        ("approval", "owner"),
        ("sha256", "9204"),
        ("pages", 0),
    ],
)
def test_a_document_entry_refuses_bad_values(field: str, value: object) -> None:
    document = {**SARS["documents"][0], field: value}
    with pytest.raises(ValidationError, match=field):
        SourceManifest.model_validate_json(json.dumps({**SARS, "documents": [document]}))


def test_write_file_writes_what_load_file_reads(tmp_path: Path) -> None:
    rate = load_file(ROOT / "data/drafts/vat/south-africa/2018-04-01.json", VatRate)
    target = tmp_path / "rate.json"
    write_file(target, rate)
    assert load_file(target, VatRate) == rate
    assert (
        target.read_bytes() == (ROOT / "data/drafts/vat/south-africa/2018-04-01.json").read_bytes()
    )


def test_load_file_refuses_a_non_canonical_file(tmp_path: Path) -> None:
    target = tmp_path / "rate.json"
    target.write_text('{"x": 1}', encoding="utf-8")
    with pytest.raises(CanonicalJsonError, match="canonical form"):
        load_file(target, VatRate)
