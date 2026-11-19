"""The committed data files agree with each other and with ADR-0012's layout (P2-6)."""

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel
from pypdf import PdfReader

from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file, load_vat_table, write_file
from munisense.provenance.sources import SourceManifest

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
TARIFF_DRAFTS = sorted((DATA / "drafts").glob("*/*/*.json"))
TARIFF_DRAFTS = [p for p in TARIFF_DRAFTS if p.parts[-3] != "vat"]
VAT_DRAFTS = sorted((DATA / "drafts" / "vat" / "south-africa").glob("*.json"))
MANIFESTS = sorted((DATA / "sources").glob("*/sources.json"))
CANONICAL_FILES = [
    *TARIFF_DRAFTS,
    *VAT_DRAFTS,
    DATA / "catalogue" / "suppliers.json",
    *MANIFESTS,
]


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(DATA)) for p in paths]


def test_the_layout_holds_the_expected_files() -> None:
    assert _ids(TARIFF_DRAFTS) == [
        "drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json",
        "drafts/city-of-ekurhuleni/2026-27/b-residential-3-phase.json",
    ]
    assert _ids(VAT_DRAFTS) == ["drafts/vat/south-africa/2018-04-01.json"]
    assert _ids(MANIFESTS) == ["sources/ekurhuleni/sources.json", "sources/sars/sources.json"]
    every = sorted((DATA / "drafts").rglob("*.json"))
    assert every == sorted([*TARIFF_DRAFTS, *VAT_DRAFTS]), "no draft outside its folder"


@pytest.mark.parametrize("path", CANONICAL_FILES, ids=_ids(CANONICAL_FILES))
def test_every_data_file_is_canonical(path: Path) -> None:
    canonical.check_bytes(path.read_bytes())


@pytest.mark.parametrize("path", TARIFF_DRAFTS, ids=_ids(TARIFF_DRAFTS))
def test_a_tariff_draft_sits_where_its_content_says(path: Path) -> None:
    version = load_file(path, TariffVersion)
    catalogue = load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue)
    first_month = catalogue.by_code(version.supplier).tariff_year_start_month.value
    start = version.effective_from.value
    first_year = start.year if start.month >= first_month else start.year - 1
    year = f"{first_year}-{(first_year + 1) % 100:02d}"
    assert (path.parts[-3], path.parts[-2], path.stem) == (
        version.supplier,
        year,
        version.tariff_code,
    )


@pytest.mark.parametrize("path", VAT_DRAFTS, ids=_ids(VAT_DRAFTS))
def test_a_vat_draft_is_named_after_its_start_date(path: Path) -> None:
    assert path.stem == load_file(path, VatRate).start.isoformat()


def test_the_vat_drafts_make_one_contiguous_table() -> None:
    assert len(load_vat_table(DATA / "drafts" / "vat" / "south-africa").rates) == len(VAT_DRAFTS)


def test_every_draft_supplier_is_in_the_catalogue() -> None:
    catalogue = load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue)
    for path in TARIFF_DRAFTS:
        catalogue.by_code(load_file(path, TariffVersion).supplier)


def test_an_unknown_supplier_is_refused() -> None:
    catalogue = load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue)
    with pytest.raises(KeyError, match="no supplier 'elsewhere'"):
        catalogue.by_code("elsewhere")


def _manifests() -> Iterator[tuple[Path, SourceManifest]]:
    for path in MANIFESTS:
        yield path.parent, load_file(path, SourceManifest)


def test_every_committed_pdf_is_listed_with_its_hash_and_page_count() -> None:
    listed = set()
    for folder, manifest in _manifests():
        for document in manifest.documents:
            path = folder / document.file
            assert hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
            assert len(PdfReader(path).pages) == document.pages
            listed.add(path)
    assert listed == set((DATA / "sources").glob("*/*.pdf"))


def test_each_manifest_agrees_with_its_readme() -> None:
    for folder, manifest in _manifests():
        readme = (folder / "README.md").read_text(encoding="utf-8")
        for document in manifest.documents:
            for written in (
                document.file,
                document.sha256,
                document.url,
                document.title,
                document.retrieved_on.isoformat(),
                document.approval,
                f"{document.pages} pages",
            ):
                # Whole words only: "E3" must not pass inside "E33", nor "2 pages" in "32 pages".
                pattern = rf"(?<![\w.-]){re.escape(written)}(?![\w-])"
                assert re.search(pattern, readme), (document.file, written)
            assert manifest.publisher in readme


def test_each_text_layer_flag_matches_the_pdf() -> None:
    """A scan yields no text on any page; a text document yields text on some page.

    The flag decides the citation check's `no_text_layer` outcome (P2-7).
    """
    for folder, manifest in _manifests():
        for document in manifest.documents:
            pages = PdfReader(folder / document.file).pages
            has_text = any(page.extract_text().strip() for page in pages)
            assert has_text is document.text_layer, document.file


def _cited_documents(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        if "document_sha256" in value:
            yield value["document_sha256"]
        for inner in value.values():
            yield from _cited_documents(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _cited_documents(inner)


def test_every_citation_names_a_listed_document() -> None:
    listed = {d.sha256 for _, m in _manifests() for d in m.documents}
    cited: set[str] = set()
    for path in [*TARIFF_DRAFTS, *VAT_DRAFTS, DATA / "catalogue" / "suppliers.json"]:
        cited |= set(_cited_documents(canonical.check_bytes(path.read_bytes())))
    assert cited
    assert cited <= listed


MODELS: dict[Path, type[BaseModel]] = {
    **dict.fromkeys(TARIFF_DRAFTS, TariffVersion),
    **dict.fromkeys(VAT_DRAFTS, VatRate),
    DATA / "catalogue" / "suppliers.json": SupplierCatalogue,
    **dict.fromkeys(MANIFESTS, SourceManifest),
}


@pytest.mark.parametrize("path", list(MODELS), ids=_ids(list(MODELS)))
def test_every_data_file_is_what_its_model_writes(path: Path, tmp_path: Path) -> None:
    """Keys in the model's order, and nothing the model would normalise (ADR-0012 s.1)."""
    target = tmp_path / path.name
    write_file(target, load_file(path, MODELS[path]))
    assert target.read_bytes() == path.read_bytes()
