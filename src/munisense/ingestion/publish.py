"""The publish step: a draft becomes an immutable publication (P2-8, ADR-0012 section 5).

`uv run poe publish <draft> --reason "..."` checks a draft and, if nothing refuses it,
writes `data/tariffs/<supplier>/<tariff-code>/<effective-from>.r<N>.json` (or
`data/vat/south-africa/<start>.r<N>.json`) with record time from the clock, and removes the
draft. `--supersedes <id>` publishes a correction; `--withdraw <id>` publishes a withdrawal
instead of a draft; `--check` runs every check and writes nothing.

Refusals (each tested):

- the draft is not canonical or not valid, or sits in the wrong folder (supplier, tariff
  year from the catalogue's start month, code; a VAT draft named after its start date);
- the supplier is not in the catalogue;
- any citation fails the citation check (P2-7), which also covers a document not in a
  manifest and a file that is not the listed document;
- a `Verified` value whose declared text check differs from the computed one;
- `--supersedes` or `--withdraw` names a publication that does not exist, is a withdrawal,
  or is already superseded; a correction that supersedes a publication of another tariff;
- the new version overlaps, in valid time, a current publication of the same tariff that it
  does not supersede (so a mid-year amendment must publish the shortening revision first);
- the record time is not later than that of the publication it supersedes;
- the target path already exists.

A publication that supersedes nothing takes the next free revision under its date (the
provisional reading in `munisense.provenance.publication`, W18). A withdrawal records the
publish step's checks with zero citation counts: it holds no values to check.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.citations import TextCheck, Verified
from munisense.domain.money import VatRate
from munisense.domain.tariffs import FreeBasicAllocation, TariffVersion
from munisense.ingestion.citation_check import (
    CitationResult,
    Outcome,
    check_citations,
    iter_cited,
)
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file
from munisense.provenance.errors import ProvenanceError
from munisense.provenance.publication import (
    VAT_CODE,
    VAT_SCOPE,
    ParsedId,
    TariffPublication,
    VatRatePublication,
    load_bytes,
    render,
)
from munisense.provenance.sources import SourceDocument, SourceManifest

TOOL_VERSION = "munisense publish 1"
"""A fixed label (the package has no version yet); raise the number when the checks change."""
DOCUMENTS_CHECKED = "all cited documents in a manifest; hashes match"

Checker = Callable[[BaseModel, dict[str, tuple[Path, SourceDocument]]], list[CitationResult]]
Clock = Callable[[], datetime]


class PublishRefusedError(Exception):
    """The draft or request cannot be published. `reasons` lists every refusal found."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Existing:
    """A publication already on disk."""

    path: Path
    id: str
    published_at: datetime
    supersedes: str | None
    start: date | None
    end: date | None
    """Valid time `[start, end)`; both `None` for a withdrawal."""

    @property
    def is_withdrawal(self) -> bool:
        return self.start is None


@dataclass
class Result:
    """What publishing did (or, with `--check`, would do)."""

    target: Path
    publication_id: str
    citations: list[CitationResult] = field(default_factory=list)
    written: bool = False
    draft_not_removed: str | None = None
    """Set when the publication was written but the draft could not be removed."""


def _now() -> datetime:
    return datetime.now(UTC)


def _documents(data: Path) -> dict[str, tuple[Path, SourceDocument]]:
    documents: dict[str, tuple[Path, SourceDocument]] = {}
    for manifest in sorted((data / "sources").glob("*/sources.json")):
        for document in load_file(manifest, SourceManifest).documents:
            if document.sha256 in documents:
                msg = f"document {document.sha256} is listed in two manifests"
                raise ProvenanceError(msg)
            documents[document.sha256] = (manifest.parent / document.file, document)
    return documents


def _valid_period(version: TariffVersion | VatRate) -> tuple[date, date | None]:
    if isinstance(version, VatRate):
        return version.start, version.end
    end = version.effective_to.value if version.effective_to is not None else None
    return version.effective_from.value, end


def _overlaps(a: tuple[date, date | None], b: tuple[date, date | None]) -> bool:
    (a_start, a_end), (b_start, b_end) = a, b
    return (b_end is None or a_start < b_end) and (a_end is None or b_start < a_end)


def _folder(data: Path, scope: str, code: str) -> Path:
    if scope == VAT_SCOPE:
        return data / "vat" / code
    return data / "tariffs" / scope / code


def _load_existing(data: Path, scope: str, code: str) -> list[Existing]:
    found = []
    for path in sorted(_folder(data, scope, code).glob("*.json")):
        publication: TariffPublication | VatRatePublication
        if scope == VAT_SCOPE:
            publication = load_bytes(path.read_bytes(), VatRatePublication)
        else:
            publication = load_bytes(path.read_bytes(), TariffPublication)
        record = publication.publication
        parsed = ParsedId.of(record.id)
        if (parsed.scope, parsed.code) != (scope, code) or path.name != (
            f"{parsed.effective_from.isoformat()}.r{parsed.revision}.json"
        ):
            msg = f"{path} does not match its id {record.id}"
            raise ProvenanceError(msg)
        start, end = (None, None)
        if publication.version is not None:
            start, end = _valid_period(publication.version)
        found.append(Existing(path, record.id, record.published_at, record.supersedes, start, end))
    return found


def _successors(existing: list[Existing]) -> dict[str, str]:
    return {e.supersedes: e.id for e in existing if e.supersedes is not None}


def _check_target(existing: list[Existing], target_id: str, reasons: list[str]) -> None:
    """The publication to supersede or withdraw, refusing what may not be superseded."""
    by_id = {e.id: e for e in existing}
    if target_id not in by_id:
        reasons.append(f"{target_id} is not a publication of this tariff")
        return
    target = by_id[target_id]
    if target.is_withdrawal:
        reasons.append(f"{target_id} is a withdrawal; republish with no supersedes instead")
    if target_id in _successors(existing):
        reasons.append(f"{target_id} is already superseded by {_successors(existing)[target_id]}")


def _next_revision(existing: list[Existing], day: date) -> int:
    revisions = [
        ParsedId.of(e.id).revision for e in existing if ParsedId.of(e.id).effective_from == day
    ]
    return max(revisions, default=0) + 1


def _text_check_reasons(model: BaseModel, results: list[CitationResult]) -> list[str]:
    computed = {r.path: r.outcome for r in results}
    expected = {TextCheck.PASSED: Outcome.PASSED, TextCheck.NO_TEXT_LAYER: Outcome.NO_TEXT_LAYER}
    reasons = []
    for path, cited in iter_cited(model):
        status = cited.status
        if isinstance(status, Verified) and computed.get(path) is not expected[status.text_check]:
            reasons.append(
                f"{path}: verified with text check {status.text_check.value}, "
                f"but the citation check gives {computed.get(path)}"
            )
    return reasons


@dataclass(frozen=True)
class Request:
    """What to publish. Exactly one of `draft` and `withdraw` is set."""

    reason: str
    published_by: str = "owner"
    draft: Path | None = None
    supersedes: str | None = None
    withdraw: str | None = None
    check_only: bool = False


def _load_draft(data: Path, draft: Path) -> tuple[TariffVersion | VatRate, str, str, list[str]]:
    """The draft's version, scope and code, and any refusal about where it sits."""
    drafts = (data / "drafts").resolve()
    resolved = draft.resolve()
    if not resolved.is_relative_to(drafts) or not resolved.is_file():
        raise PublishRefusedError([f"{draft} is not a draft file under {data / 'drafts'}"])
    relative = resolved.relative_to(drafts)
    if relative.parts[0] == "vat":
        rate = load_file(draft, VatRate)
        reasons = []
        if relative.parts[1:] != (VAT_CODE, f"{rate.start.isoformat()}.json"):
            reasons.append(
                f"a VAT draft sits at drafts/vat/{VAT_CODE}/<start>.json, not {relative}"
            )
        return rate, VAT_SCOPE, VAT_CODE, reasons
    version = load_file(draft, TariffVersion)
    if any(isinstance(c, FreeBasicAllocation) for c in version.components):
        # E49: all of TD-10 before the first tariff with a free basic allocation is published.
        return (
            version,
            version.supplier,
            version.tariff_code,
            ["a free basic allocation cannot be published until TD-10 is done (E49)"],
        )
    catalogue = load_file(data / "catalogue" / "suppliers.json", SupplierCatalogue)
    try:
        supplier = catalogue.by_code(version.supplier)
    except KeyError:
        return (
            version,
            version.supplier,
            version.tariff_code,
            [f"supplier {version.supplier} is not in the catalogue"],
        )
    year = supplier.tariff_year(version.effective_from.value)
    expected = (version.supplier, year, f"{version.tariff_code}.json")
    reasons = (
        []
        if relative.parts == expected
        else [f"this draft belongs at drafts/{'/'.join(expected)}, not drafts/{relative}"]
    )
    return version, version.supplier, version.tariff_code, reasons


def publish(  # one refusal list, built in order
    data: Path, request: Request, clock: Clock = _now, checker: Checker = check_citations
) -> Result:
    """Check `request` against the files under `data` and publish it unless refused."""
    reasons: list[str] = []
    version: TariffVersion | VatRate | None = None
    if request.withdraw is not None:
        withdrawn = ParsedId.of(request.withdraw)
        scope, code, day = withdrawn.scope, withdrawn.code, withdrawn.effective_from
        supersedes: str | None = request.withdraw
    else:
        if request.draft is None:
            raise PublishRefusedError(["give a draft to publish, or --withdraw <id>"])
        version, scope, code, reasons = _load_draft(data, request.draft)
        day = _valid_period(version)[0]
        supersedes = request.supersedes
    existing = _load_existing(data, scope, code)
    if supersedes is not None:
        _check_target(existing, supersedes, reasons)
    revision = ParsedId.of(supersedes).revision + 1 if supersedes else _next_revision(existing, day)
    publication_id = f"{scope}/{code}/{day.isoformat()}/r{revision}"
    target_path = _folder(data, scope, code) / f"{day.isoformat()}.r{revision}.json"
    result = Result(target_path, publication_id)
    counts = {"passed": 0, "no_text_layer": 0, "failed": 0}
    if version is not None:
        result.citations = checker(version, _documents(data))
        for cited in result.citations:
            counts[cited.outcome.value] += 1
            if cited.outcome is Outcome.FAILED:
                reasons.append(f"citation {cited.path} (page {cited.page}): {cited.reason}")
        reasons.extend(_text_check_reasons(version, result.citations))
        successors = _successors(existing)
        for other in existing:
            current = other.id not in successors and not other.is_withdrawal
            if other.start is None or not current or other.id == supersedes:
                continue
            if _overlaps(_valid_period(version), (other.start, other.end)):
                reasons.append(f"overlaps {other.id} in valid time without superseding it")
    if target_path.exists():
        reasons.append(f"{target_path.name} already exists")
    published_at = clock()
    latest = max(existing, key=lambda e: e.published_at, default=None)
    if published_at.utcoffset() is None:
        reasons.append("the clock gave a time without an offset")
    elif latest is not None and published_at <= latest.published_at:
        # Record time only moves forward within a tariff, so a mid-year amendment's new
        # version can never be recorded before the revision that made room for it.
        reasons.append(f"the record time is not later than that of {latest.id}")
    if reasons:
        raise PublishRefusedError(reasons)
    body = {
        "schema_version": 1,
        "publication": {
            "id": publication_id,
            "published_at": published_at.isoformat(),
            "published_by": request.published_by,
            "supersedes": supersedes,
            "reason": request.reason,
            "checks": {
                "tool_version": TOOL_VERSION,
                "schema": "valid",
                "documents": DOCUMENTS_CHECKED,
                "overlap": "none",
                "citation_check": counts,
            },
        },
        "version": canonical.parse(version.model_dump_json()) if version is not None else None,
    }
    kind = VatRatePublication if scope == VAT_SCOPE else TariffPublication
    try:
        text = render(kind.model_validate_json(canonical.dumps(body)))
    except ValidationError as error:
        raise PublishRefusedError(
            [
                f"the publication is not valid: {'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in error.errors()
            ]
        ) from None
    if request.check_only:
        return result
    _write_new(target_path, text.encode("utf-8"))
    result.written = True
    if request.draft is not None:
        try:
            request.draft.unlink()
        except OSError as error:
            result.draft_not_removed = f"{type(error).__name__}: {error}"
    return result


def _write_new(target: Path, data: bytes) -> None:
    """Write `data` to `target` atomically, never replacing an existing file.

    A temporary file in the same folder is written and synced, then hard-linked to the
    target (which fails if the target exists) and removed, so a crash leaves either no
    publication or a complete one.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "xb") as handle:  # "x": a fresh file
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main(
    argv: Sequence[str] | None = None,
    data: Path | None = None,
    clock: Clock = _now,
    checker: Checker = check_citations,
) -> int:
    parser = argparse.ArgumentParser(prog="poe publish", description=__doc__.split("\n")[0])
    parser.add_argument("draft", nargs="?", type=Path, help="the draft file to publish")
    parser.add_argument("--reason", required=True, help="why this is published (recorded)")
    parser.add_argument("--supersedes", help="the publication id this corrects")
    parser.add_argument("--withdraw", help="the publication id to withdraw (no draft)")
    parser.add_argument("--by", default="owner", help="pseudonymous handle (default: owner)")
    parser.add_argument("--check", action="store_true", help="check only; write nothing")
    args = parser.parse_args(argv)
    if (args.draft is None) == (args.withdraw is None) or (args.withdraw and args.supersedes):
        parser.error("give either a draft (optionally with --supersedes) or --withdraw <id>")
    root = data or Path.cwd() / "data"
    request = Request(
        reason=args.reason,
        published_by=args.by,
        draft=args.draft,
        supersedes=args.supersedes,
        withdraw=args.withdraw,
        check_only=args.check,
    )
    try:
        result = publish(root, request, clock, checker)
    except PublishRefusedError as refused:
        sys.stderr.write("refused:\n" + "".join(f"  - {r}\n" for r in refused.reasons))
        return 1
    except (ProvenanceError, ValidationError, ValueError, OSError) as error:
        sys.stderr.write(f"refused: {type(error).__name__}: {str(error)[:300]}\n")
        return 1
    verb = "would publish" if request.check_only else "published"
    sys.stdout.write(f"{verb} {result.publication_id} at {result.target}\n")
    for cited in result.citations:
        sys.stdout.write(f"  {cited.outcome.value:13} {cited.path} (page {cited.page})\n")
    if result.draft_not_removed is not None:
        sys.stderr.write(f"published, but could not remove the draft: {result.draft_not_removed}\n")
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover  # the command line runs main()
    raise SystemExit(main())
