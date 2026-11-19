"""The deterministic citation check against the committed PDFs (P2-7, ADR-0012 section 5).

Tests that start the extraction process are marked `slow` (about half a second each):
`poe verify` and CI run them, `poe check` does not (E43).
"""

import dataclasses
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import Configuration

from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion import citation_check, pdf_text
from munisense.ingestion.citation_check import (
    ExtractionError,
    Limits,
    Outcome,
    _outcome,  # the decision table is tested directly
    _parse_output,  # the output checks are tested directly
    check_citations,
    extract_pages,
    iter_cited,
    normalise,
    read_document,
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


def _entry(path: Path) -> SourceDocument:
    return next(d for p, d in _documents().values() if p == path)


def _rate(**changes: object) -> VatRate:
    """The VAT draft with both of its citations changed."""
    rate = load_file(VAT_DRAFT, VatRate)
    updates = {}
    for name in ("start_cited", "percent"):
        cited = getattr(rate, name)
        updates[name] = cited.model_copy(
            update={"citation": cited.citation.model_copy(update=changes)}
        )
    return rate.model_copy(update=updates)


def _done(stdout: bytes, returncode: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(["child"], returncode, stdout, b"")


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
def test_whitespace_is_normalised(text: str, normalised: str) -> None:
    assert normalise(text) == normalised


@pytest.mark.parametrize(
    ("printed", "page", "text_layer", "outcome", "reason"),
    [
        ("standard rate", "at the  standard\nrate of 15%", True, Outcome.PASSED, "found"),
        (" standard\n  rate ", "the standard rate", True, Outcome.PASSED, "found"),
        ("standard" + chr(0xA0) + "rate", "the standard rate", True, Outcome.PASSED, "found"),
        ("standard rate", "at the reduced rate", True, Outcome.FAILED, "not found"),
        ("Standard Rate", "standard rate", True, Outcome.FAILED, "not found"),
        ("standard rate", "  \n ", True, Outcome.FAILED, "but the page has none"),
        ("01 JULY 2026", "", False, Outcome.NO_TEXT_LAYER, "scanned page"),
        ("01 JULY 2026", "01 JULY 2026", False, Outcome.FAILED, "but the page has text"),
        ("  ", "anything", True, Outcome.FAILED, "printed text is empty"),
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


def test_every_pypdf_limit_is_pinned() -> None:
    fields = {f.name for f in dataclasses.fields(Configuration)}
    assert set(pdf_text.PYPDF_LIMITS) == fields - pdf_text.NOT_LIMITS
    assert pdf_text.PYPDF_LIMITS["jbig2dec_binary"] is None


# --- fast: the file must be the listed document ---------------------------------------


def test_the_listed_document_is_read() -> None:
    assert read_document(VAT_404, _entry(VAT_404), Limits()) == VAT_404.read_bytes()


def test_a_file_with_other_bytes_is_not_the_listed_document(tmp_path: Path) -> None:
    other = tmp_path / "vat-404.pdf"
    other.write_bytes(VAT_404.read_bytes() + b"\n")
    with pytest.raises(ExtractionError, match="not the listed document"):
        read_document(other, _entry(VAT_404), Limits())


def test_a_symlink_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "vat-404.pdf"
    link.symlink_to(VAT_404)
    with pytest.raises(ExtractionError, match=r"not a regular file|cannot be read \(OSError\)"):
        read_document(link, _entry(VAT_404), Limits())


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match=r"cannot be read \(FileNotFoundError\)"):
        read_document(tmp_path / "gone.pdf", _entry(VAT_404), Limits())


def test_an_over_size_file_is_refused_before_it_is_read() -> None:
    with pytest.raises(ExtractionError, match="more than the limit of 1000"):
        read_document(VAT_404, _entry(VAT_404), replace(Limits(), file_bytes=1000))


def test_a_file_that_grows_while_read_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real_fstat = os.fstat

    def small(descriptor: int) -> object:
        info = real_fstat(descriptor)
        return type("Info", (), {"st_mode": info.st_mode, "st_size": 10})()

    monkeypatch.setattr(os, "fstat", small)
    with pytest.raises(ExtractionError, match="grew past the limit"):
        read_document(VAT_404, _entry(VAT_404), replace(Limits(), file_bytes=1000))


def test_a_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "vat-404.pdf"
    os.mkfifo(fifo)
    with pytest.raises(ExtractionError, match="not a regular file"):
        read_document(fifo, _entry(VAT_404), Limits())


def test_a_citation_of_an_unlisted_document_fails_without_reading_anything() -> None:
    results = check_citations(_rate(document_sha256="0" * 64), _documents())
    assert {(r.outcome, r.reason) for r in results} == {
        (Outcome.FAILED, "the cited document is not in a source manifest")
    }


def test_a_manifest_entry_for_another_document_fails() -> None:
    documents = _documents()
    sha256 = load_file(VAT_DRAFT, VatRate).percent.citation.document_sha256
    documents[sha256] = (VAT_404, _entry(SCHEDULE))
    results = check_citations(load_file(VAT_DRAFT, VatRate), documents)
    assert {r.reason for r in results} == {
        "the manifest entry does not describe the cited document"
    }


def test_a_swapped_file_fails_closed(tmp_path: Path) -> None:
    swapped = tmp_path / "vat-404.pdf"
    swapped.write_bytes(SCHEDULE.read_bytes())
    documents = _documents()
    sha256 = _entry(VAT_404).sha256
    documents[sha256] = (swapped, documents[sha256][1])
    results = check_citations(load_file(VAT_DRAFT, VatRate), documents)
    assert {r.outcome for r in results} == {Outcome.FAILED}
    assert {r.reason for r in results} == {
        "vat-404.pdf is not the listed document (its SHA-256 differs)"
    }


# --- fast: the child's output must have exactly the expected shape ---------------------


@pytest.mark.parametrize(
    ("stdout", "returncode", "message"),
    [
        (b'{"page_count": 1, "pages": {"15": "x"}}', -9, "exit code -9"),
        (b'{"page_count": 1, "pages": {"15": "x"}}', 1, "exit code 1"),
        (b"", 0, "without a result"),
        (b'{"page_count": 1, "pa', 0, "without a result"),
        (b"\xff\xfe", 0, "without a result"),
        (b'["x"]', 0, "wrong shape"),
        (b'"x"', 0, "wrong shape"),
        (b'{"pages": {"15": "x"}}', 0, "wrong shape"),
        (b'{"page_count": 1, "pages": {}}', 0, "wrong shape"),
        (b'{"page_count": 1, "pages": {"15": "x", "16": "y"}}', 0, "wrong shape"),
        (b'{"page_count": 1, "pages": {"15": 7}}', 0, "wrong shape"),
        (b'{"page_count": true, "pages": {"15": "x"}}', 0, "wrong shape"),
        (b'{"page_count": 1, "pages": {"15": "x"}, "extra": 1}', 0, "wrong shape"),
        (b'{"error": 5}', 0, "wrong shape"),
    ],
)
def test_output_of_the_wrong_shape_or_a_failed_exit_fails(
    stdout: bytes, returncode: int, message: str
) -> None:
    with pytest.raises(ExtractionError, match=message):
        _parse_output(_done(stdout, returncode), [15], Limits())


def test_output_larger_than_the_limit_fails() -> None:
    with pytest.raises(ExtractionError, match="larger than 10 bytes"):
        _parse_output(
            _done(b'{"page_count": 1, "pages": {"15": "x"}}'),
            [15],
            replace(Limits(), output_bytes=10),
        )


def test_a_child_error_is_reported_without_control_characters() -> None:
    with pytest.raises(ExtractionError) as raised:
        _parse_output(_done(json.dumps({"error": "bad\x1b[31m\nline"}).encode()), [15], Limits())
    assert str(raised.value) == "bad?[31m?line"


def test_a_process_that_cannot_start_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise OSError

    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(ExtractionError, match=r"could not run \(OSError\)"):
        extract_pages(b"%PDF", [1], Limits())


def test_a_page_count_that_differs_from_the_manifest_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        citation_check, "extract_pages", lambda *_: (175, {15: "standard rate of 15%"})
    )
    results = check_citations(load_file(VAT_DRAFT, VatRate), _documents())
    assert {r.reason for r in results} == {"the document has 175 pages, but the manifest says 176"}


# --- fast: the child, in process (its limits are not applied here) ---------------------


def test_the_child_extracts_pages_without_changing_global_state() -> None:
    from pypdf import get_configuration

    before = get_configuration()
    result = pdf_text.extract(VAT_404.read_bytes(), [15], maximum_pages=5_000)
    assert result["page_count"] == 176
    assert "standard rate of 15%" in normalise(str(result["pages"]["15"]))  # type: ignore[index]
    assert get_configuration() is before


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
    result = pdf_text.extract(VAT_404.read_bytes(), pages, maximum_pages=maximum)
    assert message in str(result["error"])


def test_the_child_main_sets_its_limits_first_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(pdf_text, "set_limits", lambda a, c: calls.append((a, c)))
    request = json.dumps(
        {"pages": [1], "maximum_pages": 10, "file_bytes": 100, "address_space": 7, "cpu_seconds": 3}
    )
    assert pdf_text.main(["pdf_text.py", request], io.BytesIO(b"%PDF-1.7\nnot really")) == 0
    assert calls == [(7, 3)]
    assert json.loads(capsys.readouterr().out)["error"] in {"PdfReadError", "PdfStreamError"}


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
    count, texts = extract_pages(SCHEDULE.read_bytes(), list(range(1, 38)), Limits())
    assert count == 37
    assert not any(normalise(t) for t in texts.values())


@pytest.mark.slow
def test_a_wrong_printed_text_fails_as_not_found() -> None:
    results = check_citations(_rate(printed_text="at the standard rate of 16%"), _documents())
    assert {(r.outcome, r.reason) for r in results} == {
        (Outcome.FAILED, "printed text not found on the cited page")
    }


@pytest.mark.slow
def test_a_wrong_page_fails_as_not_found() -> None:
    results = check_citations(_rate(page=16), _documents())
    assert {(r.outcome, r.reason) for r in results} == {
        (Outcome.FAILED, "printed text not found on the cited page")
    }


@pytest.mark.slow
def test_a_page_past_the_end_fails_every_citation_of_that_document() -> None:
    results = check_citations(_rate(page=500), _documents())
    assert {r.outcome for r in results} == {Outcome.FAILED}
    assert all("page 500 does not exist" in r.reason for r in results)


@pytest.mark.slow
def test_a_broken_pdf_fails_closed_in_the_child() -> None:
    with pytest.raises(ExtractionError, match=r"Pdf(Read|Stream)Error"):
        extract_pages(b"%PDF-1.7\nnot really a pdf", [1], Limits())


@pytest.mark.slow
@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (replace(Limits(), timeout_seconds=0.01), r"took longer than 0\.01 s"),
        (replace(Limits(), address_space_bytes=40 * 1024**2), r"MemoryError|exit code"),
        (replace(Limits(), cpu_seconds=1), r"exit code -9"),  # soft = hard: SIGKILL
    ],
    ids=["wall-clock timeout", "memory limit", "cpu limit"],
)
def test_each_resource_limit_fails_closed(limits: Limits, message: str) -> None:
    with pytest.raises(ExtractionError, match=message):
        extract_pages(VAT_404.read_bytes(), list(range(1, 177)), limits)


@pytest.mark.slow
def test_the_child_cannot_write_file_content(tmp_path: Path) -> None:
    """RLIMIT_FSIZE is 0: the child's own limits applied, then an unbuffered write fails."""
    probe = tmp_path / "probe"
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); import pdf_text;"
        " pdf_text.set_limits(2**31, 10); open(sys.argv[2], 'wb', buffering=0).write(b'x')"
    )
    done = subprocess.run(  # noqa: S603  # fixed arguments, no shell
        [sys.executable, "-I", "-c", script, str(Path(pdf_text.__file__).parent), str(probe)],
        capture_output=True,
        env={},
        check=False,
    )
    assert b"File too large" in done.stderr
    assert probe.stat().st_size == 0


@pytest.mark.slow
def test_the_limits_hold_a_wide_margin() -> None:
    """Every page of every committed document, under a fifth of each limit (E50).

    The tightest margin is CPU time: a fifth is 24 s, against 5.7 to 11.4 s measured.
    """
    fifth = Limits(
        timeout_seconds=Limits().timeout_seconds / 5,
        cpu_seconds=Limits().cpu_seconds // 5,
        address_space_bytes=Limits().address_space_bytes // 5,
        file_bytes=Limits().file_bytes // 5,
        pages=Limits().pages // 5,
        output_bytes=Limits().output_bytes // 5,
    )
    for path, document in _documents().values():
        count, _ = extract_pages(
            read_document(path, document, fifth), list(range(1, document.pages + 1)), fifth
        )
        assert count == document.pages


def test_set_limits_sets_hard_limits_on_everything_the_child_needs_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import resource

    calls: dict[int, tuple[int, int]] = {}
    monkeypatch.setattr(resource, "setrlimit", lambda which, value: calls.update({which: value}))
    pdf_text.set_limits(123, 4)
    assert calls == {
        resource.RLIMIT_AS: (123, 123),
        resource.RLIMIT_CPU: (4, 4),
        resource.RLIMIT_FSIZE: (0, 0),
        resource.RLIMIT_CORE: (0, 0),
        resource.RLIMIT_NOFILE: (64, 64),
    }
