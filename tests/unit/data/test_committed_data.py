"""The committed data files agree with each other and with ADR-0012's layout (P2-6, P2-13)."""

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel

from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.money import VatRate, VatTable
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion.citation_check import (
    Limits,
    Outcome,
    check_citations,
    extract_pages,
    read_document,
)
from munisense.ingestion.guards import check_set, load_all
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file, load_vat_table, write_file
from munisense.provenance.publication import (
    TariffPublication,
    VatRatePublication,
    load_bytes,
    render,
)
from munisense.provenance.sources import SourceManifest
from support.publishing import DRAFTS as FIXTURE_DRAFTS

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
TARIFF_PUBLICATIONS = sorted((DATA / "tariffs").rglob("*.json"))
VAT_PUBLICATIONS = sorted((DATA / "vat").rglob("*.json"))
MANIFESTS = sorted((DATA / "sources").glob("*/sources.json"))
CANONICAL_FILES = [
    *TARIFF_PUBLICATIONS,
    *VAT_PUBLICATIONS,
    DATA / "catalogue" / "suppliers.json",
    *MANIFESTS,
]


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(DATA)) for p in paths]


# A publication's path: tariffs/<supplier>/<tariff code>/<start>.r<revision>.json, or
# vat/<country>/<start>.r<revision>.json (ADR-0012). The guards check it against the content.
TARIFF_PATH = re.compile(
    r"tariffs/[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*/\d{4}-\d{2}-\d{2}\.r[1-9]\d*\.json"
)
VAT_PATH = re.compile(r"vat/[a-z0-9]+(-[a-z0-9]+)*/\d{4}-\d{2}-\d{2}\.r[1-9]\d*\.json")


def test_the_layout_holds_the_expected_files() -> None:
    """The publications known to exist are there, and every one sits where the layout says.

    Not the exact set: a data-only pull request that adds publications must pass these
    tests without touching code (architect, P4-13 stop).
    """
    assert {
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/2026-07-01.r1.json",
        "tariffs/city-of-ekurhuleni/b-residential-3-phase/2026-07-01.r1.json",
    } <= set(_ids(TARIFF_PUBLICATIONS))
    assert {"vat/south-africa/2018-04-01.r1.json"} <= set(_ids(VAT_PUBLICATIONS))
    assert [p for p in _ids(TARIFF_PUBLICATIONS) if not TARIFF_PATH.fullmatch(p)] == []
    assert [p for p in _ids(VAT_PUBLICATIONS) if not VAT_PATH.fullmatch(p)] == []
    # Nothing else under the publication folders: a stray file would escape these checks.
    assert sorted(p for p in (DATA / "tariffs").rglob("*") if p.is_file()) == TARIFF_PUBLICATIONS
    assert sorted(p for p in (DATA / "vat").rglob("*") if p.is_file()) == VAT_PUBLICATIONS
    assert _ids(MANIFESTS) == [
        "sources/ekurhuleni/sources.json",
        "sources/eskom/sources.json",
        "sources/sars/sources.json",
    ]
    # Every draft committed before P2-13 was published, then deleted (E55). A draft
    # committed later is checked by the draft tests below, and is never one already
    # published (its publication pull request deletes it).
    assert _already_published(DATA) == []


def _already_published(data: Path) -> list[Path]:
    """Committed tariff drafts whose version (supplier, code, effective date) is published."""
    found = []
    for draft in _tariff_drafts(data / "drafts"):
        version = load_file(draft, TariffVersion)
        folder = data / "tariffs" / version.supplier / version.tariff_code
        if list(folder.glob(f"{version.effective_from.value.isoformat()}.r*.json")):
            found.append(draft)
    return found


def test_a_draft_already_published_is_found(tmp_path: Path) -> None:
    source = FIXTURE_DRAFTS / "city-of-ekurhuleni/2026-27/b-residential-1-phase.json"
    draft = tmp_path / "drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json"
    draft.parent.mkdir(parents=True)
    draft.write_bytes(source.read_bytes())
    folder = tmp_path / "tariffs/city-of-ekurhuleni/b-residential-1-phase"
    folder.mkdir(parents=True)
    assert _already_published(tmp_path) == []
    (folder / "2027-07-01.r1.json").write_text("{}", encoding="utf-8")  # another year
    assert _already_published(tmp_path) == []
    (folder / "2026-07-01.r1.json").write_text("{}", encoding="utf-8")
    assert _already_published(tmp_path) == [draft]


def test_each_committed_draft_is_its_fixture_copy() -> None:
    """The tests check the fixture copies (E62); a committed draft must be the same bytes,
    so what the owner checks and publishes is what was tested. Passes when no draft is
    committed, so a publication pull request can delete the drafts without touching code."""
    for draft in sorted((DATA / "drafts").rglob("*.json")):
        fixture = FIXTURE_DRAFTS / draft.relative_to(DATA / "drafts")
        assert fixture.is_file(), draft
        assert draft.read_bytes() == fixture.read_bytes(), draft


# ------------------------------------------------- drafts (committed ones, and the fixtures)
#
# `data/drafts/` may hold no draft (none from P2-13 to P4-13), so each check also runs on
# the fixture drafts (`tests/fixtures/drafts/`): a check that never meets a draft could not
# fail. These checks read whatever is committed and pass when nothing is.

DRAFT_ROOTS = {"committed": DATA / "drafts", "fixtures": FIXTURE_DRAFTS}


def _tariff_drafts(root: Path) -> list[Path]:
    return [p for p in sorted(root.glob("*/*/*.json")) if p.parts[-3] != "vat"]


def _vat_drafts(root: Path) -> list[Path]:
    return sorted((root / "vat" / "south-africa").glob("*.json"))


def _catalogue() -> SupplierCatalogue:
    return load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue)


def test_the_fixture_drafts_are_the_published_ones_and_homeflex() -> None:
    assert [str(p.relative_to(FIXTURE_DRAFTS)) for p in _tariff_drafts(FIXTURE_DRAFTS)] == [
        "city-of-ekurhuleni/2026-27/b-residential-1-phase.json",
        "city-of-ekurhuleni/2026-27/b-residential-3-phase.json",
        "eskom-direct/2026-27/homeflex-1.json",
        "eskom-direct/2026-27/homeflex-2.json",
        "eskom-direct/2026-27/homeflex-3.json",
        "eskom-direct/2026-27/homeflex-4.json",
    ]
    assert [p.name for p in _vat_drafts(FIXTURE_DRAFTS)] == ["2018-04-01.json"]


@pytest.mark.parametrize("root", DRAFT_ROOTS.values(), ids=DRAFT_ROOTS.keys())
def test_no_draft_sits_outside_its_folder(root: Path) -> None:
    every = sorted(root.rglob("*.json"))
    assert every == sorted([*_tariff_drafts(root), *_vat_drafts(root)])


@pytest.mark.parametrize("root", DRAFT_ROOTS.values(), ids=DRAFT_ROOTS.keys())
def test_each_draft_is_canonical_and_what_its_model_writes(root: Path, tmp_path: Path) -> None:
    drafts: list[tuple[Path, type[BaseModel]]] = [
        *((p, TariffVersion) for p in _tariff_drafts(root)),
        *((p, VatRate) for p in _vat_drafts(root)),
    ]
    for path, model in drafts:
        canonical.check_bytes(path.read_bytes())
        target = tmp_path / path.name
        write_file(target, load_file(path, model))
        assert target.read_bytes() == path.read_bytes(), path


@pytest.mark.parametrize("root", DRAFT_ROOTS.values(), ids=DRAFT_ROOTS.keys())
def test_each_tariff_draft_sits_where_its_content_says(root: Path) -> None:
    catalogue = _catalogue()
    for path in _tariff_drafts(root):
        version = load_file(path, TariffVersion)  # its supplier must be in the catalogue
        first_month = catalogue.by_code(version.supplier).tariff_year_start_month.value
        start = version.effective_from.value
        first_year = start.year if start.month >= first_month else start.year - 1
        year = f"{first_year}-{(first_year + 1) % 100:02d}"
        assert (path.parts[-3], path.parts[-2], path.stem) == (
            version.supplier,
            year,
            version.tariff_code,
        )


@pytest.mark.parametrize("root", DRAFT_ROOTS.values(), ids=DRAFT_ROOTS.keys())
def test_each_vat_draft_is_named_after_its_start_and_the_rates_join_up(root: Path) -> None:
    for path in _vat_drafts(root):
        assert path.stem == load_file(path, VatRate).start.isoformat()
    if _vat_drafts(root):
        folder = root / "vat" / "south-africa"
        assert len(load_vat_table(folder).rates) == len(_vat_drafts(root))


@pytest.mark.parametrize("path", CANONICAL_FILES, ids=_ids(CANONICAL_FILES))
def test_every_data_file_is_canonical(path: Path) -> None:
    canonical.check_bytes(path.read_bytes())


def test_the_publications_pass_the_whole_set_rules() -> None:
    """Paths, ids, suppliers in the catalogue, successors (the guards' rules, P2-9)."""
    loaded, problems = load_all(DATA)
    assert problems == []
    assert check_set(DATA, loaded) == []
    assert len(loaded) == len(TARIFF_PUBLICATIONS) + len(VAT_PUBLICATIONS)


def test_the_published_vat_rates_make_one_contiguous_table() -> None:
    rates = []
    for path in VAT_PUBLICATIONS:
        version = load_bytes(path.read_bytes(), VatRatePublication).version
        assert version is not None
        rates.append(version)
    assert len(VatTable(rates=tuple(sorted(rates, key=lambda r: r.start))).rates) == len(rates)


def test_an_unknown_supplier_is_refused() -> None:
    catalogue = load_file(DATA / "catalogue" / "suppliers.json", SupplierCatalogue)
    with pytest.raises(KeyError, match="no supplier 'elsewhere'"):
        catalogue.by_code("elsewhere")


def _manifests() -> Iterator[tuple[Path, SourceManifest]]:
    for path in MANIFESTS:
        yield path.parent, load_file(path, SourceManifest)


def test_every_committed_pdf_is_listed_with_its_hash() -> None:
    listed = set()
    for folder, manifest in _manifests():
        for document in manifest.documents:
            path = folder / document.file
            assert hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
            listed.add(path)
    assert listed == set((DATA / "sources").glob("*/*.pdf"))


@pytest.mark.slow
def test_each_page_count_and_text_layer_flag_matches_the_pdf() -> None:
    """Read every page through the citation check's limited child process (P2-7), which
    also checks the file's size and hash: these tests never parse a committed PDF in the
    test process itself (P4-2 security review). Slow (whole documents), so it runs in
    `poe verify` and CI, not in `poe check` (E43).

    A scan yields no text on any page; a text document yields text on some page. The flag
    decides the citation check's `no_text_layer` outcome.
    """
    for folder, manifest in _manifests():
        for document in manifest.documents:
            data = read_document(folder / document.file, document, Limits())
            count, texts = extract_pages(data, list(range(1, document.pages + 1)), Limits())
            assert count == document.pages, document.file
            has_text = any(text.strip() for text in texts.values())
            assert has_text is document.text_layer, document.file


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


def _cited_documents(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        if "document_sha256" in value:
            yield value["document_sha256"]
        for inner in value.values():
            yield from _cited_documents(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _cited_documents(inner)


def test_every_catalogue_citation_passes_the_citation_check() -> None:
    """The catalogue's cited values are tariff data too (CLAUDE.md rule 1): each printed
    text is on its cited page, or the page is a scan (Ekurhuleni)."""
    documents = {d.sha256: (folder / d.file, d) for folder, m in _manifests() for d in m.documents}
    results = check_citations(_catalogue(), documents)
    assert results
    assert {(r.path, r.outcome) for r in results} == {
        ("suppliers[0].tariff_year_start_month", Outcome.NO_TEXT_LAYER),
        ("suppliers[1].tariff_year_start_month", Outcome.PASSED),
    }


def test_every_citation_names_a_listed_document() -> None:
    listed = {d.sha256 for _, m in _manifests() for d in m.documents}
    cited: set[str] = set()
    drafts = [
        path
        for root in DRAFT_ROOTS.values()
        for path in [*_tariff_drafts(root), *_vat_drafts(root)]
    ]
    for path in [
        *TARIFF_PUBLICATIONS,
        *VAT_PUBLICATIONS,
        *drafts,
        DATA / "catalogue" / "suppliers.json",
    ]:
        cited |= set(_cited_documents(canonical.check_bytes(path.read_bytes())))
    assert cited
    assert cited <= listed


MODELS: dict[Path, type[BaseModel]] = {
    DATA / "catalogue" / "suppliers.json": SupplierCatalogue,
    **dict.fromkeys(MANIFESTS, SourceManifest),
}


@pytest.mark.parametrize("path", list(MODELS), ids=_ids(list(MODELS)))
def test_every_data_file_is_what_its_model_writes(path: Path, tmp_path: Path) -> None:
    """Keys in the model's order, and nothing the model would normalise (ADR-0012 s.1)."""
    target = tmp_path / path.name
    write_file(target, load_file(path, MODELS[path]))
    assert target.read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    "path",
    [*TARIFF_PUBLICATIONS, *VAT_PUBLICATIONS],
    ids=_ids([*TARIFF_PUBLICATIONS, *VAT_PUBLICATIONS]),
)
def test_every_publication_is_what_its_model_writes(path: Path) -> None:
    """A publication read and rendered again gives the same bytes (ADR-0012 s.1)."""
    publication: TariffPublication | VatRatePublication
    if path in VAT_PUBLICATIONS:
        publication = load_bytes(path.read_bytes(), VatRatePublication)
    else:
        publication = load_bytes(path.read_bytes(), TariffPublication)
    assert render(publication).encode("utf-8") == path.read_bytes()
