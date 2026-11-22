"""The deterministic citation check (P2-7, ADR-0012 section 5, ADR-0006).

For each cited value, the printed text must appear on the cited page of the cited
document. Whitespace is normalised on both sides: every run of whitespace (as Python's
`str.isspace` defines it) becomes one space, and the ends are trimmed. Outcomes:

- `passed`: the normalised printed text is in the normalised page text;
- `no_text_layer`: only when the manifest says the document has no text layer *and* the
  page yields no text;
- `failed`: everything else, including an empty printed text, a document not in a
  manifest, a file that is not the listed document (not a regular file, the wrong size or
  the wrong SHA-256), extraction errors, time-outs, output of the wrong shape, a page count
  that differs from the manifest, empty text from a document said to have a text layer,
  and text on a page of a document said to have none. The check fails closed.

The parent reads the file once, checks its size and SHA-256 against the manifest, and sends
exactly those bytes to a separate `python -I` process (`pdf_text.py`) on standard input,
with an empty environment and a wall-clock timeout; the child sets its own address-space,
CPU, file-size, core-dump and file-descriptor limits before importing pypdf (E50). Nothing
here runs inside the API or console.
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from munisense.domain.citations import iter_cited
from munisense.provenance.sources import SourceDocument

CHILD = Path(__file__).with_name("pdf_text.py")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


@dataclass(frozen=True)
class Limits:
    """Each far above what the committed documents need (E50).

    Measured needs (P2-7, on the owner's machine): extracting all 176 pages of VAT 404, the
    largest committed document (3.3 MB), took 5.7 to 11.4 s of the child's CPU time over
    three runs (`resource.getrusage(RUSAGE_CHILDREN)`), about the same wall time, and 45 MB
    peak resident memory; peak address space about 64 MB (`/proc/self/status` VmPeak).
    Margins against the worst run: CPU and wall time about 10x and 26x, address space over
    30x, file size about 20x, pages about 28x. `test_the_limits_hold_a_wide_margin` re-runs
    every page of every committed document under a fifth of each limit on every
    `poe verify`. A citation check itself reads only the cited pages, in well under a second.

    Eskom's documents (P4-2, three runs each, `getrusage(RUSAGE_CHILDREN)` around a
    whole-document `extract_pages`): the 7.2 MB schedule took 1.5 to 1.6 s of CPU time and
    the book 1.1 s. Address space was found by retrying with a lower `address_space_bytes`:
    each fits in 128 MB and fails in 96 MB (not the VmPeak method above, so not directly
    comparable). With the schedule the margins shrink: file size about 9x (a fifth of the
    limit, 12.8 MiB, leaves about 1.9x over the schedule), address space about 16x to 21x,
    CPU and wall time still above 10x (set by VAT 404).
    """

    timeout_seconds: float = 300.0
    cpu_seconds: int = 120
    """Below the wall-clock timeout, so a busy child is stopped by CPU time first."""
    address_space_bytes: int = 2 * 1024**3
    file_bytes: int = 64 * 1024**2
    pages: int = 5_000
    output_bytes: int = 64 * 1024**2


class Outcome(StrEnum):
    """The citation check's result for one cited value (ADR-0012 section 5)."""

    PASSED = "passed"
    NO_TEXT_LAYER = "no_text_layer"
    FAILED = "failed"


@dataclass(frozen=True)
class CitationResult:
    """One cited value's outcome, with where it sits in the model and why."""

    path: str
    page: int
    outcome: Outcome
    reason: str


class ExtractionError(Exception):
    """Extraction did not produce page text; the citations it was for fail."""


def normalise(text: str) -> str:
    """Every run of whitespace (`str.isspace`) to one space; the ends trimmed."""
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: str) -> str:
    return CONTROL_CHARACTERS.sub("?", text)[:200]


def read_document(path: Path, document: SourceDocument, limits: Limits) -> bytes:
    """The file's bytes, if and only if it is the listed document."""
    try:
        # Opened without following a symlink and without blocking (a FIFO), then checked on
        # the open descriptor itself, so the file checked is the file read.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                msg = f"{path.name} is not a regular file"
                raise ExtractionError(msg)
            if info.st_size > limits.file_bytes:
                size, limit = info.st_size, limits.file_bytes
                msg = f"{path.name} is {size} bytes, more than the limit of {limit}"
                raise ExtractionError(msg)
            data = handle.read(limits.file_bytes + 1)
    except OSError as error:
        msg = f"{path.name} cannot be read ({type(error).__name__})"
        raise ExtractionError(msg) from None
    if len(data) > limits.file_bytes:
        msg = f"{path.name} grew past the limit of {limits.file_bytes} bytes while being read"
        raise ExtractionError(msg)
    if hashlib.sha256(data).hexdigest() != document.sha256:
        msg = f"{path.name} is not the listed document (its SHA-256 differs)"
        raise ExtractionError(msg)
    return data


def extract_pages(data: bytes, pages: list[int], limits: Limits) -> tuple[int, dict[int, str]]:
    """(page count, text of each page in `pages`), extracted in a limited child process."""
    request = json.dumps(
        {
            "pages": pages,
            "maximum_pages": limits.pages,
            "file_bytes": limits.file_bytes,
            "address_space": limits.address_space_bytes,
            "cpu_seconds": limits.cpu_seconds,
        }
    )
    try:
        done = subprocess.run(  # noqa: S603  # a fixed interpreter and script, no shell
            [sys.executable, "-I", str(CHILD), request],
            input=data,
            capture_output=True,
            timeout=limits.timeout_seconds,
            env={},
            cwd="/",
            check=False,
        )
    except subprocess.TimeoutExpired:
        msg = f"extraction took longer than {limits.timeout_seconds} s"
        raise ExtractionError(msg) from None
    except (OSError, subprocess.SubprocessError) as error:
        msg = f"the extraction process could not run ({type(error).__name__})"
        raise ExtractionError(msg) from None
    return _parse_output(done, pages, limits)


def _parse_output(
    done: subprocess.CompletedProcess[bytes], pages: list[int], limits: Limits
) -> tuple[int, dict[int, str]]:
    if done.returncode != 0:
        msg = f"the extraction process ended with exit code {done.returncode}"
        raise ExtractionError(msg)
    if len(done.stdout) > limits.output_bytes:
        msg = f"the extraction output is larger than {limits.output_bytes} bytes"
        raise ExtractionError(msg)
    try:
        result = json.loads(done.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        msg = "the extraction process ended without a result"
        raise ExtractionError(msg) from None
    if isinstance(result, dict) and set(result) == {"error"} and isinstance(result["error"], str):
        raise ExtractionError(_clean(result["error"]))
    expected = {str(page) for page in pages}
    if not (
        isinstance(result, dict)
        and set(result) == {"page_count", "pages"}
        and type(result["page_count"]) is int
        and isinstance(result["pages"], dict)
        and set(result["pages"]) == expected
        and all(isinstance(text, str) for text in result["pages"].values())
    ):
        msg = "the extraction output has the wrong shape"
        raise ExtractionError(msg)
    return result["page_count"], {int(page): text for page, text in result["pages"].items()}


def _outcome(printed: str, page_text: str, *, text_layer: bool) -> tuple[Outcome, str]:
    wanted, page = normalise(printed), normalise(page_text)
    if not wanted:
        return Outcome.FAILED, "the printed text is empty"
    if not text_layer:
        if page:
            return Outcome.FAILED, "the manifest says no text layer, but the page has text"
        return Outcome.NO_TEXT_LAYER, "scanned page: no text to compare"
    if not page:
        return Outcome.FAILED, "the manifest says there is a text layer, but the page has none"
    if wanted in page:
        return Outcome.PASSED, "printed text found on the cited page"
    return Outcome.FAILED, "printed text not found on the cited page"


@dataclass(frozen=True)
class _Extracted:
    texts: dict[int, str]
    text_layer: bool


def _extract_document(
    sha256: str,
    pages: set[int],
    documents: dict[str, tuple[Path, SourceDocument]],
    limits: Limits,
) -> _Extracted | str:
    """The extracted pages of one document, or the reason every citation of it fails."""
    if sha256 not in documents:
        return "the cited document is not in a source manifest"
    path, document = documents[sha256]
    if document.sha256 != sha256:
        return "the manifest entry does not describe the cited document"
    try:
        count, texts = extract_pages(read_document(path, document, limits), sorted(pages), limits)
    except ExtractionError as error:
        return str(error)
    if count != document.pages:
        return f"the document has {count} pages, but the manifest says {document.pages}"
    return _Extracted(texts, document.text_layer)


def check_citations(
    model: BaseModel,
    documents: dict[str, tuple[Path, SourceDocument]],
    limits: Limits | None = None,
) -> list[CitationResult]:
    """Check every citation in `model`. `documents` maps SHA-256 to (file, manifest entry).

    Each document is read, hash-checked and extracted once.
    """
    limits = limits or Limits()
    cited = list(iter_cited(model))
    wanted: dict[str, set[int]] = {}
    for _, value in cited:
        wanted.setdefault(value.citation.document_sha256, set()).add(value.citation.page)
    extracted = {
        sha256: _extract_document(sha256, pages, documents, limits)
        for sha256, pages in sorted(wanted.items())
    }
    results = []
    for path, value in cited:
        citation = value.citation
        document = extracted[citation.document_sha256]
        if isinstance(document, str):
            results.append(CitationResult(path, citation.page, Outcome.FAILED, document))
            continue
        outcome, reason = _outcome(
            citation.printed_text, document.texts[citation.page], text_layer=document.text_layer
        )
        results.append(CitationResult(path, citation.page, outcome, reason))
    return results
