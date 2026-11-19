"""Publication guards, run by CI (P2-9, ADR-0012 sections 3 and 5).

`uv run poe publications-check` checks every file under `data/tariffs/` and `data/vat/`:

- every file is a publication at its own path (`<effective-from>.r<N>.json` in its tariff's
  folder); anything else, such as a temporary file left by a killed publish run, is refused;
- every publication is canonical and valid (through the converter for its schema version);
- every `supersedes` names an existing publication of the same tariff that is not a
  withdrawal; no publication has two successors; a successor's record time is later.

With `--base <ref>` it also refuses any publication that exists at the merge base and was
edited, deleted or renamed since. With `--pull-request` (pull requests only, never on
`main`, where a failure after the merge could not be fixed) it checks each publication the
change adds: record time within 24 hours of now and not in the future, and every publish
step check re-run (the citation check included) with its results compared to the checks
recorded in the file. Only added publications are re-checked: a later pypdf may extract an
old page differently, and old files cannot be edited.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from munisense.ingestion.citation_check import Outcome, check_citations
from munisense.ingestion.publish import (
    Checker,
    Clock,
    documents,
    overlaps,
    text_check_reasons,
    valid_period,
)
from munisense.provenance.errors import ProvenanceError
from munisense.provenance.publication import (
    VAT_CODE,
    ParsedId,
    TariffPublication,
    VatRatePublication,
    load_bytes,
)

RECORD_TIME_WINDOW = timedelta(hours=24)
TARIFF_FILE = re.compile(
    r"^tariffs/([^/]+)/([^/]+)/([0-9]{4}-[0-9]{2}-[0-9]{2})\.r([1-9][0-9]*)\.json$"
)
VAT_FILE = re.compile(rf"^vat/{VAT_CODE}/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})\.r([1-9][0-9]*)\.json$")


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


def load_all(data: Path) -> tuple[list[Loaded], list[str]]:
    """Every publication under `data`, and the problems with any file there."""
    loaded: list[Loaded] = []
    problems: list[str] = []
    files = sorted(
        p for folder in ("tariffs", "vat") for p in (data / folder).rglob("*") if not p.is_dir()
    )
    for path in files:
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


def check_set(loaded: list[Loaded]) -> list[str]:
    """The rules about the whole set of publications."""
    problems = []
    by_id = {p.id: p for p in loaded}
    successors: dict[str, list[str]] = {}
    for publication in loaded:
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
    return problems


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603  # a fixed program and arguments, no shell
        ["git", *args],  # noqa: S607  # git from PATH, as everywhere in CI
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def changes_since(repo: Path, base: str) -> tuple[list[str], list[str]]:
    """(paths of added publications, problems): any other change to a publication that
    exists at the merge base of `base` and HEAD is refused."""
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    listing = _git(
        repo,
        "diff",
        "--name-status",
        "--find-renames",
        merge_base,
        "HEAD",
        "--",
        "data/tariffs",
        "data/vat",
    )
    added, problems = [], []
    for line in listing.splitlines():
        status, *paths = line.split("\t")
        if status == "A":
            added.append(paths[0])
        else:
            problems.append(
                f"{' -> '.join(paths)}: a publication on the base was changed ({status})"
            )
    return added, problems


def check_added(  # one list of problems, check by check
    data: Path, loaded: list[Loaded], added: list[str], now: datetime, checker: Checker
) -> list[str]:
    """Re-run the publish step's checks on the publications a pull request adds."""
    problems = []
    by_path = {p.path.resolve(): p for p in loaded}
    sources = documents(data)
    for rel in added:
        publication = by_path.get((data.parent / rel).resolve())
        if publication is None:
            continue  # refused by load_all already
        record = publication.publication.publication
        if record.published_at > now:
            problems.append(f"{publication.id}: recorded in the future ({record.published_at})")
        elif record.published_at < now - RECORD_TIME_WINDOW:
            problems.append(
                f"{publication.id}: recorded more than 24 hours before this run; run the "
                "publish step again"
            )
        version = publication.publication.version
        counts = {"passed": 0, "no_text_layer": 0, "failed": 0}
        if version is not None:
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
        recorded = record.checks.citation_check.model_dump()
        if recorded != counts:
            problems.append(
                f"{publication.id}: the recorded citation check {recorded} differs from"
                f" this run's {counts}"
            )
    return problems


def run_checks(
    data: Path,
    base: str | None = None,
    *,
    pull_request: bool = False,
    clock: Clock = _now,
    checker: Checker = check_citations,
) -> list[str]:
    loaded, problems = load_all(data)
    problems += check_set(loaded)
    if base is not None:
        added, changed = changes_since(data.parent, base)
        problems += changed
        if pull_request:
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
    parser.add_argument("--base", help="git ref to compare with (its merge base with HEAD)")
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
            f"publications-check: git failed ({error.returncode}): {error.stderr[:300]}\n"
        )
        return 2
    if problems:
        sys.stderr.write("publications-check failed:\n" + "".join(f"  - {p}\n" for p in problems))
        return 1
    sys.stdout.write("publications-check: every publication is in order\n")
    return 0


if __name__ == "__main__":  # pragma: no cover  # the command line runs main()
    raise SystemExit(main())
