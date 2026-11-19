"""The deterministic citation check (P2-7, ADR-0012 section 5, ADR-0006).

For each cited value, the printed text must appear on the cited page of the committed
document. Whitespace is normalised on both sides: every run of Unicode whitespace becomes
one space, and the ends are trimmed. Outcomes:

- `passed`: the normalised printed text is in the normalised page text;
- `no_text_layer`: only when the manifest says the document has no text layer *and* the
  page yields no text;
- `failed`: everything else, including extraction errors, time-outs, an over-size file,
  empty text from a document said to have a text layer, and text on a page of a document
  said to have none. The check fails closed.

pypdf runs in a separate process (`pdf_text.py`) with a wall-clock timeout, an address-space
limit and a CPU-time limit, after the file size is checked; the child also refuses a
document with too many pages (E50). Only committed documents listed in a source manifest
are ever opened, and nothing here runs inside the API or console.
"""

import json
import re
import resource
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from munisense.domain.citations import Cited
from munisense.provenance.sources import SourceDocument

CHILD = Path(__file__).with_name("pdf_text.py")


@dataclass(frozen=True)
class Limits:
    """Each far above what the committed documents need (E50; measured in the P2-7 PR).

    The largest committed PDF is 3.3 MB with 176 pages; extracting all of it took 4.8 s,
    peak resident memory 42 MB and peak address space 64 MB.
    """

    timeout_seconds: float = 120.0
    cpu_seconds: int = 120
    address_space_bytes: int = 2 * 1024**3
    file_bytes: int = 64 * 1024**2
    pages: int = 5_000


class Outcome(StrEnum):
    PASSED = "passed"
    NO_TEXT_LAYER = "no_text_layer"
    FAILED = "failed"


@dataclass(frozen=True)
class CitationResult:
    path: str
    """Where the cited value sits in the checked model, for example `components[1].rate`."""
    page: int
    outcome: Outcome
    reason: str


class ExtractionError(Exception):
    """Extraction did not produce page text; the citations it was for fail."""


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def iter_cited(value: object, path: str = "") -> Iterator[tuple[str, "Cited[Any]"]]:
    # A string annotation: building Cited[Any] at runtime is refused by the float guard.
    """Every cited value in a model, depth first, with its path."""
    if isinstance(value, Cited):
        yield path, value
        return
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from iter_cited(getattr(value, name), f"{path}.{name}" if path else name)
    elif isinstance(value, tuple | list):
        for index, inner in enumerate(value):
            yield from iter_cited(inner, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from iter_cited(inner, f"{path}[{key!r}]")


def _limit(limits: Limits) -> Callable[[], None]:
    def apply() -> None:  # pragma: no cover  # runs in the child, before exec
        resource.setrlimit(resource.RLIMIT_AS, (limits.address_space_bytes,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds,) * 2)

    return apply


def extract_pages(path: Path, pages: list[int], limits: Limits) -> dict[int, str]:
    """The text of `pages` of the PDF at `path`, extracted in a limited child process."""
    size = path.stat().st_size
    if size > limits.file_bytes:
        msg = f"{path.name} is {size} bytes, more than the limit of {limits.file_bytes}"
        raise ExtractionError(msg)
    request = json.dumps({"path": str(path), "pages": pages, "maximum_pages": limits.pages})
    try:
        done = subprocess.run(  # noqa: S603  # a fixed interpreter and script, no shell
            [sys.executable, "-I", str(CHILD), request],
            capture_output=True,
            timeout=limits.timeout_seconds,
            preexec_fn=_limit(limits),  # single-threaded caller
            check=False,
        )
    except subprocess.TimeoutExpired:
        msg = f"extraction from {path.name} took longer than {limits.timeout_seconds} s"
        raise ExtractionError(msg) from None
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        msg = f"extraction from {path.name} ended without a result (exit {done.returncode})"
        raise ExtractionError(msg) from None
    if "error" in result:
        raise ExtractionError(str(result["error"]))
    return {int(page): text for page, text in result["pages"].items()}


def _outcome(printed: str, page_text: str, *, text_layer: bool) -> tuple[Outcome, str]:
    page = normalise(page_text)
    if not text_layer:
        if page:
            return Outcome.FAILED, "the manifest says no text layer, but the page has text"
        return Outcome.NO_TEXT_LAYER, "scanned page: no text to compare"
    if not page:
        return Outcome.FAILED, "the manifest says there is a text layer, but the page has none"
    if normalise(printed) in page:
        return Outcome.PASSED, "printed text found on the cited page"
    return Outcome.FAILED, "printed text not found on the cited page"


def check_citations(
    model: BaseModel,
    documents: dict[str, tuple[Path, SourceDocument]],
    limits: Limits | None = None,
) -> list[CitationResult]:
    """Check every citation in `model`. `documents` maps SHA-256 to (file, manifest entry).

    A citation of a document not in `documents` fails. Each document is opened once.
    """
    limits = limits or Limits()
    cited = list(iter_cited(model))
    wanted: dict[str, set[int]] = {}
    for _, value in cited:
        wanted.setdefault(value.citation.document_sha256, set()).add(value.citation.page)
    texts: dict[str, dict[int, str] | str] = {}
    for sha256, pages in sorted(wanted.items()):
        if sha256 not in documents:
            texts[sha256] = "the cited document is not in a source manifest"
            continue
        try:
            texts[sha256] = extract_pages(documents[sha256][0], sorted(pages), limits)
        except ExtractionError as error:
            texts[sha256] = str(error)
    results = []
    for path, value in cited:
        sha256, page = value.citation.document_sha256, value.citation.page
        extracted = texts[sha256]
        if isinstance(extracted, str):
            results.append(CitationResult(path, page, Outcome.FAILED, extracted))
            continue
        outcome, reason = _outcome(
            value.citation.printed_text,
            extracted[page],
            text_layer=documents[sha256][1].text_layer,
        )
        results.append(CitationResult(path, page, outcome, reason))
    return results
