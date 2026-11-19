"""The deterministic citation check against the committed PDFs (P2-7, ADR-0012 section 5).

Tests that start the extraction process are marked `slow` (about half a second each):
`poe verify` and CI run them, `poe check` does not (E43).
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion import pdf_text
from munisense.ingestion.citation_check import (
    ExtractionError,
    Limits,
    Outcome,
    _outcome,  # the decision table is tested directly
    check_citations,
    extract_pages,
    iter_cited,
    normalise,
)
from munisense.provenance.drafts import load_file
from munisense.provenance.sources import SourceDocument, SourceManifest

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
VAT_DRAFT = DATA / "drafts/vat/south-africa/2018-04-01.json"
TARIFF_DRAFTS = sorted((DATA / "drafts/city-of-ekurhuleni").glob("*/*.json"))
VAT_404 = DATA / "sources/sars/vat-404-guide-for-vendors-2025-01.pdf"
SCHEDULE = DATA / "sources/ekurhuleni/electricity-tariffs-2026-27-signed.pdf"


def _documents() -> dict[str, tuple[Path, SourceDocument]]:
    documents = {}
    for manifest in sorted((DATA / "sources").glob("*/sources.json")):
        for document in load_file(manifest, SourceManifest).documents:
            documents[document.sha256] = (manifest.parent / document.file, document)
    return documents


def _with_citation(rate: VatRate, **changes: object) -> VatRate:
    percent = rate.percent.model_copy(
        update={"citation": rate.percent.citation.model_copy(update=changes)}
    )
    return rate.model_copy(update={"percent": percent})


# --- fast: the rules themselves -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "normalised"),
    [
        ("  at the\nstandard\t\trate  ", "at the standard rate"),
        ("15" + chr(0xA0) + "%", "15 %"),  # a no-break space is whitespace too
        ("a" + chr(0x2028) + "b" + chr(0x3000) + "c", "a b c"),  # line and ideographic spaces
        ("", ""),
    ],
)
def test_whitespace_is_normalised_on_unicode_whitespace(text: str, normalised: str) -> None:
    assert normalise(text) == normalised


@pytest.mark.parametrize(
    ("printed", "page", "text_layer", "outcome", "reason"),
    [
        ("standard rate", "at the  standard\nrate of 15%", True, Outcome.PASSED, "found"),
        ("standard rate", "at the reduced rate", True, Outcome.FAILED, "not found"),
        ("standard rate", "  \n ", True, Outcome.FAILED, "but the page has none"),
        ("01 JULY 2026", "", False, Outcome.NO_TEXT_LAYER, "scanned page"),
        ("01 JULY 2026", "01 JULY 2026", False, Outcome.FAILED, "but the page has text"),
        ("Standard Rate", "standard rate", True, Outcome.FAILED, "not found"),
    ],
)
def test_the_outcome_rules_fail_closed(
    printed: str, page: str, *, text_layer: bool, outcome: Outcome, reason: str
) -> None:
    got, why = _outcome(printed, page, text_layer=text_layer)
    assert got is outcome
    assert reason in why


@pytest.mark.parametrize("path", [VAT_DRAFT, *TARIFF_DRAFTS], ids=lambda p: p.name)
def test_the_walker_finds_every_citation_in_the_file(path: Path) -> None:
    def count(value: object) -> int:
        if isinstance(value, dict):
            own = 1 if {"citation", "status"} <= value.keys() else 0
            return own + sum(count(v) for v in value.values())
        if isinstance(value, list):
            return sum(count(v) for v in value)
        return 0

    model = load_file(path, VatRate if path == VAT_DRAFT else TariffVersion)
    assert len(list(iter_cited(model))) == count(json.loads(path.read_text("utf-8")))


def test_the_walker_looks_inside_mappings() -> None:
    rate = load_file(VAT_DRAFT, VatRate)
    assert [path for path, _ in iter_cited({"x": [rate.percent]})] == ["['x'][0]"]


def test_the_child_extracts_pages_in_process() -> None:
    result = pdf_text.extract(str(VAT_404), [15], maximum_pages=5_000)
    assert "standard rate of 15%" in normalise(str(result["pages"]["15"]))  # type: ignore[index]


@pytest.mark.parametrize(
    ("pages", "maximum", "message"),
    [
        ([177], 5_000, "page 177 does not exist"),
        ([0], 5_000, "page 0 does not exist"),
        ([1], 100, "more than the limit of 100"),
    ],
)
def test_the_child_refuses_missing_pages_and_long_documents(
    pages: list[int], maximum: int, message: str
) -> None:
    assert message in str(pdf_text.extract(str(VAT_404), pages, maximum_pages=maximum)["error"])


def test_the_child_reports_any_failure_as_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot really a pdf")
    request = json.dumps({"path": str(broken), "pages": [1], "maximum_pages": 10})
    assert pdf_text.main(["pdf_text.py", request]) == 0
    assert "error" in json.loads(capsys.readouterr().out)


def test_an_over_size_file_is_refused_before_any_process_starts() -> None:
    with pytest.raises(ExtractionError, match="more than the limit of 1000"):
        extract_pages(VAT_404, [15], replace(Limits(), file_bytes=1000))


def test_a_citation_of_an_unlisted_document_fails() -> None:
    rate = _with_citation(load_file(VAT_DRAFT, VatRate), document_sha256="0" * 64)
    by_path = {r.path: r for r in check_citations(rate, _documents())}
    assert by_path["percent"].outcome is Outcome.FAILED
    assert "not in a source manifest" in by_path["percent"].reason


# --- slow: through the limited child process ------------------------------------------


@pytest.mark.slow
def test_both_vat_404_page_15_printed_texts_pass() -> None:
    results = check_citations(load_file(VAT_DRAFT, VatRate), _documents())
    assert [(r.path, r.page, r.outcome) for r in results] == [
        ("start_cited", 15, Outcome.PASSED),
        ("percent", 15, Outcome.PASSED),
    ]


@pytest.mark.slow
@pytest.mark.parametrize("path", TARIFF_DRAFTS, ids=lambda p: p.name)
def test_every_tariff_b_citation_is_on_a_scan(path: Path) -> None:
    results = check_citations(load_file(path, TariffVersion), _documents())
    assert results
    assert {r.outcome for r in results} == {Outcome.NO_TEXT_LAYER}


@pytest.mark.slow
def test_every_page_of_the_ekurhuleni_schedule_yields_no_text() -> None:
    texts = extract_pages(SCHEDULE, list(range(1, 38)), Limits())
    assert len(texts) == 37
    assert not any(normalise(t) for t in texts.values())


@pytest.mark.slow
def test_a_wrong_printed_text_fails() -> None:
    rate = _with_citation(load_file(VAT_DRAFT, VatRate), printed_text="at the standard rate of 16%")
    by_path = {r.path: r for r in check_citations(rate, _documents())}
    assert by_path["percent"].outcome is Outcome.FAILED
    assert by_path["start_cited"].outcome is Outcome.PASSED


@pytest.mark.slow
def test_a_wrong_page_fails() -> None:
    rate = _with_citation(load_file(VAT_DRAFT, VatRate), page=16)
    by_path = {r.path: r for r in check_citations(rate, _documents())}
    assert by_path["percent"].outcome is Outcome.FAILED


@pytest.mark.slow
def test_a_page_past_the_end_fails_every_citation_of_that_document() -> None:
    rate = _with_citation(load_file(VAT_DRAFT, VatRate), page=500)
    results = check_citations(rate, _documents())
    assert {r.outcome for r in results} == {Outcome.FAILED}
    assert all("page 500 does not exist" in r.reason for r in results)


@pytest.mark.slow
def test_an_extraction_error_fails_closed(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot really a pdf")
    documents = _documents()
    sha256 = load_file(VAT_DRAFT, VatRate).percent.citation.document_sha256
    documents[sha256] = (broken, documents[sha256][1])
    results = check_citations(load_file(VAT_DRAFT, VatRate), documents)
    assert {r.outcome for r in results} == {Outcome.FAILED}


@pytest.mark.slow
@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (replace(Limits(), timeout_seconds=0.01), "took longer than 0.01 s"),
        (replace(Limits(), address_space_bytes=40 * 1024**2), "MemoryError|ended without a result"),
        (replace(Limits(), cpu_seconds=1), "ended without a result"),
    ],
    ids=["wall-clock timeout", "memory limit", "cpu limit"],
)
def test_each_resource_limit_fails_closed(limits: Limits, message: str) -> None:
    with pytest.raises(ExtractionError, match=rf"{message}"):
        extract_pages(VAT_404, list(range(1, 177)), limits)


def test_the_default_limits_are_far_above_the_measured_needs() -> None:
    """Measured on the owner's machine (P2-7): 4.8 s, 42 MB resident, 64 MB address space."""
    limits = Limits()
    largest = max(p.stat().st_size for p in (DATA / "sources").glob("*/*.pdf"))
    assert limits.timeout_seconds >= 20 * 4.8
    assert limits.address_space_bytes >= 20 * 64 * 1024**2
    assert limits.file_bytes >= 15 * largest
    assert limits.pages >= 20 * 176
