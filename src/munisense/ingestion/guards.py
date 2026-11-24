"""Publication guards, run by CI (P2-9, ADR-0012 sections 3 and 5).

`uv run poe publications-check` checks every file under `data/tariffs/` and `data/vat/`:

- the folders are spelled exactly so (no case variant such as `data/Tariffs/`), and nothing
  under them is a symbolic link;
- every file is a publication at its own path (`<effective-from>.r<N>.json` in its tariff's
  folder); anything else, such as a temporary file left by a killed publish run, is refused;
- every publication is canonical and valid (through the converter for its schema version),
  names a supplier in the catalogue, and holds no free basic allocation while TD-10 is open
  (E49);
- a version's recorded citation check has a `drawn` count exactly when its tool label is
  "munisense publish 3" or later: a label-2 file with one, or a label-3 file without one, is
  refused (ADR-0016 point 5);
- every `supersedes` names an existing publication of the same tariff that is not a
  withdrawal; no publication has two successors; a successor's record time is later; no two
  publications of one tariff share a record time.

With `--base <ref>` it also refuses any change, other than an added regular file, to the
publication folders since the merge base of that ref and HEAD (committed changes only): an
edit, deletion, rename, type change, symbolic link or submodule. With `--pull-request`
(pull requests only, never on `main`, where a failure after the merge could not be fixed)
it re-runs the publish step's checks on each added publication: record time within 24
hours of now, not in the future, and later than every other publication of the same tariff
it could follow; the citation check and `Verified` text checks, with the counts compared to
those recorded; the overlap with the publications current when it was published; and the
tool label. Only added publications are re-checked: a later pypdf may extract an old page
differently, and old files cannot be edited. A pull request that adds publications may not
add, change or remove any manifest's `drawn` list (ADR-0016 point 5): the list is a trusted
input of the citation check, so it changes apart from the publications that rely on it.

The checks run the pull request's own code, so they catch mistakes made through the normal
path; they are not a boundary against a change that also edits the guards (security
register).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from munisense.catalogue.suppliers import SupplierCatalogue
from munisense.domain.tariffs import FreeBasicAllocation
from munisense.ingestion.citation_check import Outcome, check_citations
from munisense.ingestion.publish import (
    EARLIER_TOOL_VERSIONS,
    TOOL_VERSION,
    Checker,
    Clock,
    documents,
    new_counts,
    overlaps,
    text_check_reasons,
    valid_period,
)
from munisense.provenance.drafts import load_file
from munisense.provenance.errors import ProvenanceError
from munisense.provenance.publication import (
    VAT_CODE,
    ParsedId,
    PublishChecks,
    TariffPublication,
    VatRatePublication,
    load_bytes,
)
from munisense.provenance.sources import SourceDocument

RECORD_TIME_WINDOW = timedelta(hours=24)
FOLDERS = ("tariffs", "vat")
TARIFF_FILE = re.compile(
    r"^tariffs/([^/]+)/([^/]+)/([0-9]{4}-[0-9]{2}-[0-9]{2})\.r([1-9][0-9]*)\.json$"
)
VAT_FILE = re.compile(rf"^vat/{VAT_CODE}/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})\.r([1-9][0-9]*)\.json$")
REGULAR_FILE_MODE = "100644"
REDO = "see 'Publishing' in docs/development.md to publish it again"


@dataclass(frozen=True)
class Loaded:
    path: Path
    publication: TariffPublication | VatRatePublication

    @property
    def id(self) -> str:
        return self.publication.publication.id

    @property
    def published_at(self) -> datetime:
        return self.publication.publication.published_at

    @property
    def supersedes(self) -> str | None:
        return self.publication.publication.supersedes

    @property
    def key(self) -> tuple[str, str]:
        return ParsedId.of(self.id).key


def _now() -> datetime:
    return datetime.now(UTC)


def _files(data: Path, problems: list[str]) -> list[Path]:
    """Every file under the publication folders, refusing links and case variants."""
    found: list[Path] = []
    if data.is_dir():
        for entry in sorted(data.iterdir()):
            if entry.name.casefold() in FOLDERS and entry.name not in FOLDERS:
                problems.append(f"{entry.name}/: a case variant of a publication folder")
    for folder in FOLDERS:
        top = data / folder
        if top.is_symlink():
            problems.append(f"{folder}/: a symbolic link, not a folder")
            continue
        for current, dirs, files in os.walk(top):  # does not follow links
            for name in sorted(dirs + files):
                path = Path(current) / name
                if path.is_symlink():
                    problems.append(f"{path.relative_to(data).as_posix()}: a symbolic link")
            for name in sorted(files):
                path = Path(current) / name
                if path.is_symlink():
                    continue  # reported above
                if not path.is_file():  # a FIFO or device would block or mislead a read
                    problems.append(f"{path.relative_to(data).as_posix()}: not a regular file")
                    continue
                found.append(path)
    return sorted(found)


def load_all(data: Path) -> tuple[list[Loaded], list[str]]:
    """Every publication under `data`, and the problems with any file there."""
    loaded: list[Loaded] = []
    problems: list[str] = []
    for path in _files(data, problems):
        rel = path.relative_to(data).as_posix()
        tariff, vat = TARIFF_FILE.match(rel), VAT_FILE.match(rel)
        if tariff is None and vat is None:
            problems.append(f"{rel}: not a publication (only <date>.r<N>.json files belong here)")
            continue
        try:
            publication: TariffPublication | VatRatePublication
            if vat is not None:
                publication = load_bytes(path.read_bytes(), VatRatePublication)
                expected = f"vat/{VAT_CODE}/{vat.group(1)}/r{vat.group(2)}"
            else:
                assert tariff is not None  # noqa: S101  # one of the two matched
                publication = load_bytes(path.read_bytes(), TariffPublication)
                expected = "/".join(tariff.groups()[:3]) + f"/r{tariff.group(4)}"
        except (ProvenanceError, ValidationError, OSError) as error:
            problems.append(f"{rel}: {type(error).__name__}: {str(error)[:200]}")
            continue
        if publication.publication.id != expected:
            problems.append(
                f"{rel}: its path says {expected}, but its id is {publication.publication.id}"
            )
            continue
        loaded.append(Loaded(path, publication))
    return loaded, problems


def check_set(data: Path, loaded: list[Loaded]) -> list[str]:  # one rule per block
    """The rules about every publication and about the whole set."""
    problems = []
    try:
        catalogue = load_file(data / "catalogue" / "suppliers.json", SupplierCatalogue)
        suppliers = {s.code for s in catalogue.suppliers}
    except (ProvenanceError, ValidationError, OSError) as error:
        problems.append(f"catalogue/suppliers.json: {type(error).__name__}: {str(error)[:200]}")
        suppliers = None  # unreadable: reported once above, not as every supplier unknown
    by_id = {p.id: p for p in loaded}
    successors: dict[str, list[str]] = {}
    times: dict[tuple[tuple[str, str], datetime], str] = {}
    for publication in loaded:
        if (
            isinstance(publication.publication, TariffPublication)
            and (version := publication.publication.version) is not None
        ):
            if suppliers is not None and publication.key[0] not in suppliers:
                problems.append(
                    f"{publication.id}: supplier {publication.key[0]} is not in the catalogue"
                )
            if any(isinstance(c, FreeBasicAllocation) for c in version.components):
                problems.append(
                    f"{publication.id}: a free basic allocation cannot be published until TD-10"
                    " is done (E49)"
                )
        problems.extend(_drawn_count_shape(publication))
        moment = (publication.key, publication.published_at)
        if moment in times:
            problems.append(f"{publication.id} and {times[moment]} share a record time")
        times[moment] = publication.id
        target = publication.supersedes
        if target is None:
            continue
        successors.setdefault(target, []).append(publication.id)
        if target not in by_id:
            problems.append(f"{publication.id} supersedes {target}, which does not exist")
            continue
        if by_id[target].publication.version is None:
            problems.append(f"{publication.id} supersedes {target}, which is a withdrawal")
        if publication.published_at <= by_id[target].published_at:
            problems.append(
                f"{publication.id} is not recorded later than {target}, which it supersedes"
            )
    for target, ids in sorted(successors.items()):
        if len(ids) > 1:
            problems.append(f"{target} has more than one successor: {', '.join(sorted(ids))}")
    revisions: dict[tuple[str, str, str], set[int]] = {}
    for publication in loaded:
        parsed = ParsedId.of(publication.id)
        revisions.setdefault((*parsed.key, parsed.effective_from.isoformat()), set()).add(
            parsed.revision
        )
    by_revision = {
        (
            *ParsedId.of(p.id).key,
            ParsedId.of(p.id).effective_from.isoformat(),
            ParsedId.of(p.id).revision,
        ): p
        for p in loaded
    }
    for (scope, code, day, revision), publication in sorted(by_revision.items()):
        before = by_revision.get((scope, code, day, revision - 1))
        if before is not None and publication.published_at <= before.published_at:
            problems.append(
                f"{publication.id} is not recorded later than {before.id}, the revision before it"
            )
    for (scope, code, day), found in sorted(revisions.items()):
        if found != set(range(1, max(found) + 1)):
            missing = sorted(set(range(1, max(found) + 1)) - found)
            problems.append(
                f"{scope}/{code}/{day}: revisions are not r1 to r{max(found)} without gaps"
                f" (missing {', '.join(f'r{n}' for n in missing)}; ADR-0013)"
            )
    return problems


def _drawn_count_shape(publication: Loaded) -> list[str]:
    """A version records a `drawn` count under the current label and never under an
    earlier one. Any other label is refused elsewhere (an added file must carry the
    current label; files on the base cannot change)."""
    checks = publication.publication.publication.checks
    if not isinstance(checks, PublishChecks):
        return []
    label, has_drawn = checks.tool_version, checks.citation_check.drawn is not None
    if label in EARLIER_TOOL_VERSIONS and has_drawn:
        return [f"{publication.id}: tool label {label!r} never records a drawn count"]
    if label == TOOL_VERSION and not has_drawn:
        return [f"{publication.id}: tool label {label!r} must record a drawn count"]
    return []


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603  # a fixed program and arguments, no shell
        ["git", "-c", "core.quotePath=false", *args],  # noqa: S607  # git from PATH, as in CI
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def changes_since(repo: Path, base: str) -> tuple[list[str], list[str]]:
    """(paths of added publications, problems) since the merge base of `base` and HEAD.

    Only an added regular file is allowed; every other change to the publication folders
    (any case spelling) is refused, including a symbolic link or a submodule.
    """
    commit = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
    merge_base = _git(repo, "merge-base", commit, "HEAD").strip()
    raw = _git(
        repo,
        "diff",
        "--raw",
        "-z",
        "--no-color",
        "--no-ext-diff",
        "--find-renames",
        merge_base,
        "HEAD",
        "--",
        ":(icase)data/tariffs",
        ":(icase)data/vat",
    )
    fields = raw.split("\0")
    added, problems = [], []
    index = 0
    while index < len(fields) - 1:
        _old_mode, new_mode, _old, _new, status = fields[index].lstrip(":").split(" ")
        count = 2 if status[0] in "RC" else 1
        paths = fields[index + 1 : index + 1 + count]
        index += 1 + count
        where = " -> ".join(paths)
        if status != "A":
            problems.append(f"{where}: a publication on the base was changed ({status})")
        elif not paths[0].startswith(("data/tariffs/", "data/vat/")):
            problems.append(f"{where}: added under a case variant of the publication folders")
        elif new_mode != REGULAR_FILE_MODE:
            problems.append(f"{where}: added as mode {new_mode}, not a regular file")
        else:
            added.append(paths[0])
    return added, problems


def _order_problems(publication: Loaded, loaded: list[Loaded], added: set[str]) -> list[str]:
    """An added publication must be recorded later than every other one of its tariff,
    except added ones recorded later still (which are checked in their turn)."""
    problems = []
    for other in loaded:
        if other is publication or other.key != publication.key:
            continue
        other_added = other.id in added
        if not other_added and other.published_at >= publication.published_at:
            problems.append(
                f"{publication.id}: recorded no later than {other.id}, which is already published"
            )
    return problems


def check_added(  # one list of problems, check by check
    data: Path, loaded: list[Loaded], added: list[str], now: datetime, checker: Checker
) -> list[str]:
    """Re-run the publish step's checks on the publications a pull request adds."""
    problems = []
    by_path = {p.path.resolve(): p for p in loaded}
    try:
        sources: dict[str, tuple[Path, SourceDocument]] | None = documents(data)
    except (ProvenanceError, ValidationError, OSError) as error:
        problems.append(f"source manifests: {type(error).__name__}: {str(error)[:200]}")
        sources = None  # the citation re-run is skipped; every other check still runs
    added_publications = []
    for rel in added:
        publication = by_path.get((data.parent / rel).resolve())
        if publication is None:
            problems.append(f"{rel}: added, but not loaded as a publication")
            continue
        added_publications.append(publication)
    added_ids = {p.id for p in added_publications}
    for publication in added_publications:
        record = publication.publication.publication
        if record.published_at > now:
            problems.append(f"{publication.id}: recorded in the future ({record.published_at})")
        elif record.published_at < now - RECORD_TIME_WINDOW:
            problems.append(
                f"{publication.id}: recorded more than 24 hours before this run; {REDO}"
            )
        problems.extend(_order_problems(publication, loaded, added_ids))
        if record.checks.tool_version != TOOL_VERSION:
            problems.append(
                f"{publication.id}: tool label {record.checks.tool_version!r}, not {TOOL_VERSION!r}"
            )
        version = publication.publication.version
        counts = new_counts()
        if version is not None and sources is None:
            continue  # cannot re-run the citation check; already reported
        if version is not None and sources is not None:
            results = checker(version, sources)
            for result in results:
                counts[result.outcome.value] += 1
                if result.outcome is Outcome.FAILED:
                    problems.append(f"{publication.id}: citation {result.path}: {result.reason}")
            problems.extend(f"{publication.id}: {r}" for r in text_check_reasons(version, results))
            earlier = [
                p
                for p in loaded
                if p.key == publication.key and p.published_at < record.published_at
            ]
            superseded = {p.supersedes for p in earlier if p.supersedes is not None}
            for other in earlier:
                other_version = other.publication.version
                if other_version is None or other.id in superseded or other.id == record.supersedes:
                    continue
                if overlaps(valid_period(version), valid_period(other_version)):
                    problems.append(
                        f"{publication.id}: overlaps {other.id}, current when it was published"
                    )
        if version is None:
            continue  # a withdrawal's own checks: its target is checked in check_set
        checks = record.checks
        assert isinstance(checks, PublishChecks)  # noqa: S101  # the envelope ties checks to a version
        # Absent means 0 (label 2; such a file is refused above by its label).
        recorded = {key: getattr(checks.citation_check, key) or 0 for key in counts}
        if recorded != counts:
            problems.append(
                f"{publication.id}: the recorded citation check {recorded} differs from"
                f" this run's {counts}"
            )
    return problems


def _drawn_lists(repo: Path, revision: str, path: str) -> dict[str, object] | None:
    """Each document's raw `drawn` list in the manifest at `path` as of `revision` (an
    absent file has none), or `None` if the file is not a JSON object with documents."""
    try:
        text = _git(repo, "show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        return {}  # not in this revision
    try:
        manifest = json.loads(text)
        return {
            str(document["sha256"]): document.get("drawn") for document in manifest["documents"]
        }
    except (json.JSONDecodeError, KeyError, TypeError, RecursionError):
        return None


def drawn_lists_unchanged(repo: Path, base: str) -> list[str]:
    """ADR-0016 point 5: a pull request that adds publications changes no `drawn` list.

    Compares the raw lists of every source manifest changed since the merge base, so any
    edit to a list (or a list added with a new document or manifest) is refused, whatever
    its formatting. Any symbolic link or submodule added, removed or changed under
    `data/sources/` is refused too: the loader follows a linked folder, so a manifest read
    through one would not be the one compared here (P4-11 security review)."""
    commit = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
    merge_base = _git(repo, "merge-base", commit, "HEAD").strip()
    raw = _git(
        repo,
        "diff",
        "--raw",
        "-z",
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        merge_base,
        "HEAD",
        "--",
        ":(icase)data/sources",
    ).split("\0")
    changed, links = [], []
    for header, path in zip(raw[0:-1:2], raw[1::2], strict=True):
        old_mode, new_mode = header.lstrip(":").split(" ")[:2]
        # The loader's glob follows a symbolic link to a folder, so a manifest could be read
        # from outside what git shows here: refuse links and submodules outright.
        if {old_mode, new_mode} - {"000000", "100644", "100755"}:
            links.append(path)
        else:
            changed.append(path)
    problems = [
        f"{path}: a symbolic link or submodule under data/sources; change it in its own"
        " pull request"
        for path in sorted(links)
    ]
    for path in sorted(changed):
        if not path.casefold().endswith("/sources.json"):
            continue
        before, after = _drawn_lists(repo, merge_base, path), _drawn_lists(repo, "HEAD", path)
        if before is None or after is None:
            problems.append(
                f"{path}: cannot compare its drawn lists; change it in its own pull request"
            )
            continue
        differs = sorted(
            sha256
            for sha256 in before.keys() | after.keys()
            if before.get(sha256) != after.get(sha256)
        )
        if differs:
            problems.append(
                f"{path}: a pull request that adds publications may not change a drawn list"
                f" (ADR-0016 point 5); changed for {', '.join(d[:12] for d in differs)}"
            )
    return problems


def data_only(repo: Path, base: str) -> list[str]:
    """W20 (E51): a pull request that adds or changes a publication changes nothing outside
    `data/`. It runs the pull request's own code: it catches accidents, not tampering."""
    commit = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
    merge_base = _git(repo, "merge-base", commit, "HEAD").strip()
    names = [
        n
        for n in _git(repo, "diff", "--name-only", "-z", "--no-renames", merge_base, "HEAD").split(
            "\0"
        )
        if n
    ]
    publications = [n for n in names if n.casefold().startswith(("data/tariffs/", "data/vat/"))]
    outside = sorted(n for n in names if not n.startswith("data/"))
    if publications and outside:
        return [
            "a pull request that adds or changes publications may change nothing outside"
            f" data/ (W20); it also changes {', '.join(outside[:5])}"
            + (" and more" if len(outside) > 5 else "")
        ]
    return []


def run_checks(
    data: Path,
    base: str | None = None,
    *,
    pull_request: bool = False,
    clock: Clock = _now,
    checker: Checker = check_citations,
) -> list[str]:
    loaded, problems = load_all(data)
    problems += check_set(data, loaded)
    if base is not None:
        added, changed = changes_since(data.parent, base)
        problems += changed
        if pull_request:
            problems += data_only(data.parent, base)
            if added:
                problems += drawn_lists_unchanged(data.parent, base)
            problems += check_added(data, loaded, added, clock(), checker)
    return problems


def main(
    argv: Sequence[str] | None = None,
    data: Path | None = None,
    clock: Clock = _now,
    checker: Checker = check_citations,
) -> int:
    parser = argparse.ArgumentParser(
        prog="poe publications-check", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--base", help="git ref to compare with (committed changes since its merge base)"
    )
    parser.add_argument(
        "--pull-request",
        action="store_true",
        help="also re-check added publications (needs --base)",
    )
    args = parser.parse_args(argv)
    if args.pull_request and args.base is None:
        parser.error("--pull-request needs --base")
    root = data or Path.cwd() / "data"
    try:
        problems = run_checks(
            root, args.base, pull_request=args.pull_request, clock=clock, checker=checker
        )
    except subprocess.CalledProcessError as error:
        sys.stderr.write(
            f"publications-check: git failed ({error.returncode}): {str(error.stderr)[:300]}\n"
        )
        return 2
    if problems:
        sys.stderr.write("publications-check failed:\n" + "".join(f"  - {p}\n" for p in problems))
        return 1
    sys.stdout.write("publications-check: every publication is in order\n")
    return 0


if __name__ == "__main__":  # pragma: no cover  # the command line runs main()
    raise SystemExit(main())
