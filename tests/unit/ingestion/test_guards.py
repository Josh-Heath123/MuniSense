"""The publication guards (P2-9): each check shown to fail on a deliberate violation.

Each test builds a throwaway git repository holding a copy of the data, publishes into it
with the real publish step (and a stand-in citation checker), and then breaks one rule.
The module is `slow` (git and file copies): `poe verify` and CI run it, `poe check` does not.
"""

import json
import os
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from munisense.domain.citations import iter_cited
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion import guards
from munisense.ingestion.citation_check import CitationResult, Outcome
from munisense.ingestion.publish import Checker, Request, publish
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file, write_file
from munisense.provenance.sources import SourceDocument
from support.builders import fixture_free_basic
from support.publishing import DRAFTS

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[3]
TARIFF = "city-of-ekurhuleni/b-residential-1-phase"
FOLDER = Path("data/tariffs") / TARIFF
START = datetime(2026, 12, 1, 9, 30, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def checker(outcome: Outcome | None = None) -> Checker:
    def check(
        model: BaseModel, _sources: dict[str, tuple[Path, SourceDocument]]
    ) -> list[CitationResult]:
        ok = Outcome.PASSED if isinstance(model, VatRate) else Outcome.NO_TEXT_LAYER
        return [
            CitationResult(path, c.citation.page, outcome or ok, "stand-in")
            for path, c in iter_cited(model)
        ]

    return check


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603  # fixed program, test arguments
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


ESKOM_MANIFEST = Path("data/sources/eskom/sources.json")


def _change_manifest_at(path: Path, change: object) -> None:
    body = json.loads(path.read_text("utf-8"))
    change(body)  # type: ignore[operator]
    path.write_text(canonical.dumps(body), encoding="utf-8")


def _list_drawn_items(body: dict[str, Any]) -> None:
    """Made-up drawn lists on both Eskom documents, committed on the base branch."""
    for document in body["documents"]:
        document["drawn"] = [{"page": 33, "what": "a test figure", "texts": ["Test 1"]}]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose main branch holds Tariff B r1 and the VAT rate r1."""
    shutil.copytree(ROOT / "data" / "catalogue", tmp_path / "data" / "catalogue")
    shutil.copytree(DRAFTS, tmp_path / "data" / "drafts")
    shutil.copytree(
        ROOT / "data" / "sources",
        tmp_path / "data" / "sources",
        ignore=shutil.ignore_patterns("*.pdf"),
    )
    _change_manifest_at(tmp_path / ESKOM_MANIFEST, _list_drawn_items)
    git(tmp_path, "init", "-q", "-b", "main")
    clock = Clock()
    data = tmp_path / "data"
    draft = data / "drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json"
    publish(data, Request(reason="t", draft=draft), clock, checker())
    vat = data / "drafts/vat/south-africa/2018-04-01.json"
    publish(data, Request(reason="t", draft=vat), clock, checker())
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first publications")
    git(tmp_path, "switch", "-q", "-c", "feat/x")
    return tmp_path


def problems(repo: Path, **options: object) -> list[str]:
    return guards.run_checks(repo / "data", checker=checker(), **options)  # type: ignore[arg-type]


def _rewrite(path: Path, change: dict[str, object]) -> None:
    body = json.loads(path.read_text("utf-8"))
    body["publication"].update(change)
    path.write_text(canonical.dumps(body), encoding="utf-8")


def _draft(repo: Path) -> Path:
    path = repo / "data/drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json"
    write_file(
        path,
        load_file(
            DRAFTS / "city-of-ekurhuleni/2026-27/b-residential-1-phase.json",
            TariffVersion,
        ),
    )
    return path


# --- the whole set --------------------------------------------------------------------


def test_a_clean_set_passes(repo: Path) -> None:
    assert problems(repo) == []
    assert problems(repo, base="main", pull_request=True, clock=lambda: START) == []


def test_a_file_that_is_not_a_publication_is_refused(repo: Path) -> None:
    (repo / FOLDER / ".2026-07-01.r2.json.99.tmp").write_bytes(b"partial")
    (repo / "data/vat/notes.md").write_text("x", encoding="utf-8")
    assert sorted(problems(repo)) == [
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/.2026-07-01.r2.json.99.tmp: not a"
        " publication (only <date>.r<N>.json files belong here)",
        "vat/notes.md: not a publication (only <date>.r<N>.json files belong here)",
    ]


def test_a_non_canonical_publication_is_refused(repo: Path) -> None:
    path = repo / FOLDER / "2026-07-01.r1.json"
    path.write_bytes(path.read_bytes().removesuffix(b"\n"))
    assert problems(repo) == [
        f"{path.relative_to(repo / 'data').as_posix()}: CanonicalJsonError: not in canonical form"
        " (two-space indentation, one final newline, no extra spaces)"
    ]


def test_a_path_that_disagrees_with_its_id_is_refused(repo: Path) -> None:
    (repo / FOLDER / "2026-07-01.r1.json").rename(repo / FOLDER / "2026-07-01.r3.json")
    assert problems(repo) == [
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/2026-07-01.r3.json: its path says"
        f" {TARIFF}/2026-07-01/r3, but its id is {TARIFF}/2026-07-01/r1"
    ]


def _second(repo: Path, clock: Clock, *, withdraw: bool = False) -> Path:
    data = repo / "data"
    if withdraw:
        publish(data, Request(reason="t", withdraw=f"{TARIFF}/2026-07-01/r1"), clock, checker())
    else:
        publish(
            data,
            Request(reason="t", draft=_draft(repo), supersedes=f"{TARIFF}/2026-07-01/r1"),
            clock,
            checker(),
        )
    return repo / FOLDER / "2026-07-01.r2.json"


def test_a_supersedes_that_names_nothing_is_refused(repo: Path) -> None:
    second = _second(repo, Clock(START + timedelta(days=1)))
    (repo / FOLDER / "2026-07-01.r1.json").unlink()
    assert (
        f"{TARIFF}/2026-07-01/r2 supersedes {TARIFF}/2026-07-01/r1, which does not exist"
        in problems(repo)
    )
    assert second.exists()


def test_superseding_a_withdrawal_is_refused(repo: Path) -> None:
    clock = Clock(START + timedelta(days=1))
    _second(repo, clock, withdraw=True)
    third = repo / FOLDER / "2026-07-01.r3.json"
    body = json.loads((repo / FOLDER / "2026-07-01.r2.json").read_text("utf-8"))
    body["publication"].update(
        {
            "id": f"{TARIFF}/2026-07-01/r3",
            "supersedes": f"{TARIFF}/2026-07-01/r2",
            "published_at": "2026-12-03T09:30:00+00:00",
        }
    )
    third.write_text(canonical.dumps(body), encoding="utf-8")
    assert problems(repo) == [
        f"{TARIFF}/2026-07-01/r3 supersedes {TARIFF}/2026-07-01/r2, which is a withdrawal"
    ]


def test_two_successors_are_refused(repo: Path) -> None:
    second = _second(repo, Clock(START + timedelta(days=1)))
    body = json.loads(second.read_text("utf-8"))
    version = TariffVersion.model_validate_json(json.dumps(body["version"]))
    moved = version.model_copy(
        update={
            "effective_from": version.effective_from.model_copy(update={"value": date(2026, 8, 1)})
        }
    )
    body["version"] = canonical.parse(moved.model_dump_json())
    body["publication"]["id"] = f"{TARIFF}/2026-08-01/r2"
    (repo / FOLDER / "2026-08-01.r2.json").write_text(canonical.dumps(body), encoding="utf-8")
    assert (
        f"{TARIFF}/2026-07-01/r1 has more than one successor:"
        f" {TARIFF}/2026-07-01/r2, {TARIFF}/2026-08-01/r2" in problems(repo)
    )


def test_a_successor_recorded_earlier_is_refused(repo: Path) -> None:
    second = _second(repo, Clock(START + timedelta(days=1)))
    _rewrite(second, {"published_at": "2026-11-01T00:00:00+00:00"})
    assert problems(repo) == [  # both orders fail: the successor and the next revision
        f"{TARIFF}/2026-07-01/r2 is not recorded later than {TARIFF}/2026-07-01/r1,"
        " which it supersedes",
        f"{TARIFF}/2026-07-01/r2 is not recorded later than {TARIFF}/2026-07-01/r1,"
        " the revision before it",
    ]


# --- changes against the base ----------------------------------------------------------


@pytest.mark.parametrize("change", ["edit", "delete", "rename"])
def test_a_publication_on_the_base_cannot_change(repo: Path, change: str) -> None:
    path = repo / FOLDER / "2026-07-01.r1.json"
    if change == "edit":
        _rewrite(path, {"reason": "edited later"})
    elif change == "delete":
        path.unlink()
    else:
        path.rename(path.with_name("2026-07-01.r9.json"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", change)
    found = problems(repo, base="main")
    assert any("a publication on the base was changed" in p for p in found), found


def test_an_added_publication_is_not_a_change(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "correction")
    assert (
        problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
        == []
    )


# --- pull requests: added publications re-checked ---------------------------------------


def _added(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "correction")


@pytest.mark.parametrize(
    ("now", "message"),
    [
        (START + timedelta(hours=25), "recorded more than 24 hours before this run"),
        (START, "recorded in the future"),
    ],
)
def test_an_added_publication_must_be_recorded_within_24_hours(
    repo: Path, now: datetime, message: str
) -> None:
    _added(repo)
    found = problems(repo, base="main", pull_request=True, clock=lambda: now)
    assert any(message in p for p in found), found


def test_the_24_hour_check_does_not_run_on_main(repo: Path) -> None:
    _added(repo)
    assert problems(repo, base="main", clock=lambda: START + timedelta(days=30)) == []


def test_a_failed_citation_in_an_added_publication_is_refused(repo: Path) -> None:
    _added(repo)
    found = guards.run_checks(
        repo / "data",
        "main",
        pull_request=True,
        clock=lambda: START + timedelta(hours=1),
        checker=checker(Outcome.FAILED),
    )
    assert any("citation printed_name: stand-in" in p for p in found), found
    assert any("differs from this run's" in p for p in found), found


def test_recorded_checks_that_differ_from_a_rerun_are_refused(repo: Path) -> None:
    _added(repo)
    path = repo / FOLDER / "2026-07-01.r2.json"
    body = json.loads(path.read_text("utf-8"))
    body["publication"]["checks"]["citation_check"] = {
        "passed": 16,
        "no_text_layer": 0,
        "drawn": 0,
        "failed": 0,
    }
    path.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "commit", "-qam", "claimed checks")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        f"{TARIFF}/2026-07-01/r2: the recorded citation check {{'passed': 16, 'no_text_layer': 0,"
        " 'drawn': 0, 'failed': 0} differs from this run's {'passed': 0, 'no_text_layer': 16,"
        " 'drawn': 0, 'failed': 0}"
    ]


def test_an_added_publication_that_overlapped_when_published_is_refused(repo: Path) -> None:
    """A file added by hand, with no supersedes, overlapping the current r1."""
    body = json.loads((repo / FOLDER / "2026-07-01.r1.json").read_text("utf-8"))
    body["publication"].update(
        {"id": f"{TARIFF}/2026-07-01/r2", "published_at": "2026-12-01T10:00:00+00:00"}
    )
    (repo / FOLDER / "2026-07-01.r2.json").write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "overlap")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        f"{TARIFF}/2026-07-01/r2: overlaps {TARIFF}/2026-07-01/r1, current when it was published"
        in found
    )


def test_a_revision_gap_is_refused(repo: Path) -> None:
    (repo / FOLDER / "2026-07-01.r1.json").rename(repo / FOLDER / "2026-07-01.r3.json")
    body = json.loads((repo / FOLDER / "2026-07-01.r3.json").read_text("utf-8"))
    body["publication"]["id"] = f"{TARIFF}/2026-07-01/r3"
    (repo / FOLDER / "2026-07-01.r3.json").write_text(canonical.dumps(body), encoding="utf-8")
    assert problems(repo) == [
        f"{TARIFF}/2026-07-01: revisions are not r1 to r3 without gaps (missing r1, r2; ADR-0013)"
    ]


def test_an_added_withdrawal_and_a_restore_pass(
    repo: Path,
) -> None:
    clock = Clock(START + timedelta(minutes=30))
    data = repo / "data"
    publish(data, Request(reason="t", withdraw=f"{TARIFF}/2026-07-01/r1"), clock, checker())
    publish(data, Request(reason="t", draft=_draft(repo)), clock, checker())  # restore: r3
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "withdraw and restore")
    assert (repo / FOLDER / "2026-07-01.r3.json").exists()
    assert (
        problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
        == []
    )


def test_a_publication_pull_request_may_change_nothing_outside_data(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    (repo / "README.md").write_text("also changed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "publication and code")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        "a pull request that adds or changes publications may change nothing outside data/"
        " (W20); it also changes README.md"
    ) in found


def test_a_code_pull_request_without_publications_may_change_anything(repo: Path) -> None:
    (repo / "README.md").write_text("code only\n", encoding="utf-8")
    (repo / "data/drafts/note.md").write_text("draft notes\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "code")
    assert problems(repo, base="main", pull_request=True, clock=lambda: START) == []


# --- the command -----------------------------------------------------------------------


def test_the_command_reports_and_exits(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = repo / "data"
    assert guards.main([], data, checker=checker()) == 0
    assert "every publication is in order" in capsys.readouterr().out
    (repo / FOLDER / "x.json").write_text("{}", encoding="utf-8")
    assert guards.main([], data, checker=checker()) == 1
    assert "publications-check failed:\n  - tariffs/" in capsys.readouterr().err


def test_the_command_reports_a_git_failure(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert guards.main(["--base", "no-such-ref"], repo / "data", checker=checker()) == 2
    assert "git failed" in capsys.readouterr().err


def test_pull_request_needs_a_base() -> None:
    with pytest.raises(SystemExit) as exited:
        guards.main(["--pull-request"])
    assert exited.value.code == 2


def test_an_added_file_that_is_not_a_publication_is_refused(repo: Path) -> None:
    (repo / FOLDER / "notes.json").write_text("{}", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "stray file")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START)
    assert found == [
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/notes.json: not a publication"
        " (only <date>.r<N>.json files belong here)",
        "data/tariffs/city-of-ekurhuleni/b-residential-1-phase/notes.json: added, but not"
        " loaded as a publication",
    ]


def test_an_earlier_version_that_does_not_overlap_is_not_refused(repo: Path) -> None:
    data = repo / "data"
    original = load_file(_draft(repo), TariffVersion)
    earlier = original.model_copy(
        update={
            "effective_from": original.effective_from.model_copy(
                update={"value": date(2025, 7, 1)}
            ),
            "effective_to": original.effective_to.model_copy(update={"value": date(2026, 7, 1)}),  # type: ignore[union-attr]
        }
    )
    path = data / "drafts/city-of-ekurhuleni/2025-26/b-residential-1-phase.json"
    path.parent.mkdir()
    write_file(path, earlier)
    clock = Clock(START + timedelta(minutes=10))
    publish(data, Request(reason="t", draft=path), clock, checker())
    publish(
        data,
        Request(reason="t", draft=_draft(repo), supersedes=f"{TARIFF}/2026-07-01/r1"),
        clock,
        checker(),
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "earlier version and a correction")
    assert (
        problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
        == []
    )


def test_the_default_clock_gives_an_offset() -> None:
    assert guards._now().utcoffset() is not None


# --- links, submodules and case variants (P2-9 reviews) -------------------------------


def test_a_symlinked_folder_under_the_publication_folders_is_refused(repo: Path) -> None:
    (repo / "data/tariffs/linked").symlink_to(repo / "data/drafts")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "link")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START)
    assert "tariffs/linked: a symbolic link" in found
    assert "data/tariffs/linked: added as mode 120000, not a regular file" in found


def test_a_symlinked_file_is_refused(repo: Path) -> None:
    link = repo / FOLDER / "2026-08-01.r1.json"
    link.symlink_to(repo / FOLDER / "2026-07-01.r1.json")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "link")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START)
    assert f"{(FOLDER / link.name).relative_to('data').as_posix()}: a symbolic link" in found
    assert any("added as mode 120000" in p for p in found), found


def test_a_submodule_under_the_publication_folders_is_refused(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},data/vat/sub")
    git(repo, "commit", "-q", "-m", "gitlink")
    found = problems(repo, base="main")
    assert "data/vat/sub: added as mode 160000, not a regular file" in found


def test_a_case_variant_publication_folder_is_refused(repo: Path) -> None:
    variant = repo / "data/Tariffs/city-of-ekurhuleni/b-residential-1-phase"
    try:
        variant.mkdir(parents=True)
    except FileExistsError:  # pragma: no cover  # a case-insensitive file system
        pytest.skip("the file system is case-insensitive")
    shutil.copy(repo / FOLDER / "2026-07-01.r1.json", variant / "2026-07-01.r2.json")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "variant")
    found = problems(repo, base="main")
    assert "Tariffs/: a case variant of a publication folder" in found


# --- the publish step's other checks (P2-9 review) -----------------------------------


def test_a_backdated_added_publication_is_refused(repo: Path) -> None:
    """Recorded before the published r1, so it would escape the overlap check."""
    body = json.loads((repo / FOLDER / "2026-07-01.r1.json").read_text("utf-8"))
    body["publication"].update(
        {"id": f"{TARIFF}/2026-07-01/r2", "published_at": "2026-12-01T09:00:00+00:00"}
    )
    (repo / FOLDER / "2026-07-01.r2.json").write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "backdated")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        f"{TARIFF}/2026-07-01/r2: recorded no later than {TARIFF}/2026-07-01/r1,"
        " which is already published" in found
    )


def test_two_publications_of_one_tariff_may_not_share_a_record_time(repo: Path) -> None:
    body = json.loads((repo / FOLDER / "2026-07-01.r1.json").read_text("utf-8"))
    body["publication"]["id"] = f"{TARIFF}/2026-07-01/r2"
    (repo / FOLDER / "2026-07-01.r2.json").write_text(canonical.dumps(body), encoding="utf-8")
    assert f"{TARIFF}/2026-07-01/r2 and {TARIFF}/2026-07-01/r1 share a record time" in problems(
        repo
    )


def test_a_published_free_basic_allocation_is_refused(repo: Path) -> None:
    path = repo / FOLDER / "2026-07-01.r1.json"
    body = json.loads(path.read_text("utf-8"))
    version = TariffVersion.model_validate_json(json.dumps(body["version"]))
    with_fba = version.model_copy(
        update={"components": (*version.components, fixture_free_basic("50"))}
    )
    body["version"] = canonical.parse(with_fba.model_dump_json())
    path.write_text(canonical.dumps(body), encoding="utf-8")
    assert problems(repo) == [
        f"{TARIFF}/2026-07-01/r1: a free basic allocation cannot be published until TD-10"
        " is done (E49)"
    ]


def test_a_supplier_not_in_the_catalogue_is_refused(repo: Path) -> None:
    catalogue = repo / "data/catalogue/suppliers.json"
    body = json.loads(catalogue.read_text("utf-8"))
    body["suppliers"][0]["code"] = "elsewhere"
    catalogue.write_text(canonical.dumps(body), encoding="utf-8")
    assert problems(repo) == [
        f"{TARIFF}/2026-07-01/r1: supplier city-of-ekurhuleni is not in the catalogue"
    ]


def test_an_unreadable_catalogue_is_reported(repo: Path) -> None:
    (repo / "data/catalogue/suppliers.json").write_text("{}", encoding="utf-8")
    found = problems(repo)
    assert len(found) == 1
    assert found[0].startswith("catalogue/suppliers.json: CanonicalJsonError")


def test_a_verified_value_that_disagrees_with_the_rerun_is_refused(repo: Path) -> None:
    _added(repo)
    path = repo / FOLDER / "2026-07-01.r2.json"
    body = json.loads(path.read_text("utf-8"))
    body["version"]["printed_name"]["status"] = {
        "kind": "verified",
        "verifier": "owner",
        "verifier_kind": "human",
        "method": "visual comparison with the scanned page",
        "verified_on": "2026-12-01",
        "text_check": "passed",
    }
    path.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "commit", "-qam", "verified")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        f"{TARIFF}/2026-07-01/r2: printed_name: verified with text check passed, but the"
        " citation check gives no_text_layer"
    ) in found


def test_a_changed_tool_label_is_refused(repo: Path) -> None:
    _added(repo)
    path = repo / FOLDER / "2026-07-01.r2.json"
    body = json.loads(path.read_text("utf-8"))
    body["publication"]["checks"]["tool_version"] = "hand made"
    path.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "commit", "-qam", "label")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert f"{TARIFF}/2026-07-01/r2: tool label 'hand made', not 'munisense publish 3'" in found


def test_unreadable_manifests_are_reported_not_raised(repo: Path) -> None:
    _added(repo)
    shutil.copy(
        repo / "data/sources/sars/sources.json", repo / "data/sources/ekurhuleni/sources.json"
    )
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        "source manifests: ProvenanceError: document"
        " 5f6e4225703d6ba2f0d19bd0911fe580f787bcab4d1f8d6f421525051366ad1e"
        " is listed in two manifests"
    ]


def test_missing_publication_folders_are_in_order(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "data" / "catalogue", tmp_path / "data" / "catalogue")
    assert guards.run_checks(tmp_path / "data") == []


@pytest.mark.parametrize("base", ["no-such-ref", "--output=/tmp/x", "0" * 40])
def test_an_unusable_base_fails_closed(
    repo: Path, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert guards.main([f"--base={base}"], repo / "data", checker=checker()) == 2
    assert "git failed" in capsys.readouterr().err


def test_the_real_citation_check_runs_on_an_added_vat_publication(repo: Path) -> None:
    for pdf in (ROOT / "data" / "sources").glob("*/*.pdf"):
        shutil.copy(pdf, repo / "data" / "sources" / pdf.parent.name / pdf.name)
    data = repo / "data"
    rate = load_file(DRAFTS / "vat/south-africa/2018-04-01.json", VatRate)
    shortened = rate.model_copy(
        update={"end_cited": rate.start_cited.model_copy(update={"value": date(2027, 1, 1)})}
    )
    draft = data / "drafts/vat/south-africa/2018-04-01.json"
    write_file(draft, shortened)
    publish(
        data,
        Request(reason="t", draft=draft, supersedes="vat/south-africa/2018-04-01/r1"),
        Clock(START + timedelta(minutes=30)),
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "shortened VAT rate")
    assert (
        guards.run_checks(data, "main", pull_request=True, clock=lambda: START + timedelta(hours=1))
        == []
    )


def test_a_publication_folder_that_is_itself_a_link_is_refused(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(ROOT / "data" / "catalogue", data / "catalogue")
    (tmp_path / "elsewhere").mkdir()
    (data / "vat").symlink_to(tmp_path / "elsewhere")
    assert guards.run_checks(data) == ["vat/: a symbolic link, not a folder"]


def test_a_missing_data_folder_has_nothing_to_check_but_the_catalogue(tmp_path: Path) -> None:
    found = guards.run_checks(tmp_path / "data")
    assert len(found) == 1
    assert found[0].startswith("catalogue/suppliers.json: FileNotFoundError")


def test_a_fifo_is_refused_without_blocking(repo: Path) -> None:
    os.mkfifo(repo / FOLDER / "2026-08-01.r1.json")
    assert problems(repo) == [
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/2026-08-01.r1.json: not a regular file"
    ]


def test_a_case_variant_of_the_data_folder_is_refused_even_on_a_push(repo: Path) -> None:
    variant = repo / "DATA/tariffs/city-of-ekurhuleni/b-residential-1-phase"
    try:
        variant.mkdir(parents=True)
    except FileExistsError:  # pragma: no cover  # a case-insensitive file system
        pytest.skip("the file system is case-insensitive")
    shutil.copy(repo / FOLDER / "2026-07-01.r1.json", variant / "2026-07-01.r2.json")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "variant")
    found = problems(repo, base="main")  # no --pull-request: as on a push to main
    assert (
        "DATA/tariffs/city-of-ekurhuleni/b-residential-1-phase/2026-07-01.r2.json: added under"
        " a case variant of the publication folders"
    ) in found


def test_unreadable_manifests_do_not_hide_the_other_checks(repo: Path) -> None:
    _added(repo)
    shutil.copy(
        repo / "data/sources/sars/sources.json", repo / "data/sources/ekurhuleni/sources.json"
    )
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(days=3))
    assert found[0].startswith("source manifests: ProvenanceError")
    assert any("recorded more than 24 hours before this run" in p for p in found), found


def test_a_later_revision_recorded_earlier_under_its_date_is_refused(repo: Path) -> None:
    clock = Clock(START + timedelta(minutes=30))
    publish(
        repo / "data", Request(reason="t", withdraw=f"{TARIFF}/2026-07-01/r1"), clock, checker()
    )
    _rewrite(repo / FOLDER / "2026-07-01.r2.json", {"published_at": "2026-12-01T09:00:00+00:00"})
    found = problems(repo)
    assert (
        f"{TARIFF}/2026-07-01/r2 is not recorded later than {TARIFF}/2026-07-01/r1,"
        " the revision before it"
    ) in found
    assert (  # the withdrawal also supersedes r1, so the successor order fails too
        f"{TARIFF}/2026-07-01/r2 is not recorded later than {TARIFF}/2026-07-01/r1,"
        " which it supersedes" in found
    )


# --- the drawn count and the drawn lists (P4-11, ADR-0016 point 5) ----------------------


def _counts_and_label(path: Path, label: str, *, drawn: bool) -> None:
    body = json.loads(path.read_text("utf-8"))
    checks = body["publication"]["checks"]
    checks["tool_version"] = label
    if drawn:
        checks["citation_check"]["drawn"] = 0
    else:
        checks["citation_check"].pop("drawn", None)
    path.write_text(canonical.dumps(body), encoding="utf-8")


@pytest.mark.parametrize(
    ("label", "drawn", "message"),
    [
        (
            "munisense publish 2",
            True,
            "tool label 'munisense publish 2' never records a drawn count",
        ),
        (
            "munisense publish 3",
            False,
            "tool label 'munisense publish 3' must record a drawn count",
        ),
    ],
)
def test_the_drawn_count_goes_with_the_label(
    repo: Path, label: str, *, drawn: bool, message: str
) -> None:
    _counts_and_label(repo / FOLDER / "2026-07-01.r1.json", label, drawn=drawn)
    assert problems(repo) == [f"{TARIFF}/2026-07-01/r1: {message}"]


def test_a_label_2_publication_without_a_drawn_count_is_in_order(repo: Path) -> None:
    _counts_and_label(repo / FOLDER / "2026-07-01.r1.json", "munisense publish 2", drawn=False)
    assert problems(repo) == []


def test_an_added_label_2_publication_is_refused(repo: Path) -> None:
    path = _second(repo, Clock(START + timedelta(minutes=30)))
    _counts_and_label(path, "munisense publish 2", drawn=False)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "an old label")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        f"{TARIFF}/2026-07-01/r2: tool label 'munisense publish 2', not 'munisense publish 3'"
    ]


def _change_manifest(repo: Path, change: object) -> None:
    path = repo / ESKOM_MANIFEST
    body = json.loads(path.read_text("utf-8"))
    change(body)  # type: ignore[operator]
    path.write_text(canonical.dumps(body), encoding="utf-8")


def _drop_book_drawn(body: dict[str, Any]) -> None:
    del body["documents"][1]["drawn"]


def _edit_a_drawn_text(body: dict[str, Any]) -> None:
    body["documents"][0]["drawn"][0]["texts"] = ["Test 2"]


def _retitle(body: dict[str, Any]) -> None:
    body["documents"][0]["title"] = "Schedule of Standard Prices"


@pytest.mark.parametrize(
    ("change", "which"), [(_drop_book_drawn, "eef82b077d7d"), (_edit_a_drawn_text, "915a93b2d71a")]
)
def test_a_publication_pull_request_may_not_change_a_drawn_list(
    repo: Path, change: object, which: str
) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    _change_manifest(repo, change)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "publication and a drawn list")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        f"{ESKOM_MANIFEST}: a pull request that adds publications may not change a drawn list"
        f" (ADR-0016 point 5); changed for {which}"
    ]


def test_a_new_manifest_with_a_drawn_list_counts_as_a_change(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    shutil.copy(repo / ESKOM_MANIFEST, repo / "data/sources/eskom2.json")
    (repo / "data/sources/other").mkdir()
    shutil.move(repo / "data/sources/eskom2.json", repo / "data/sources/other/sources.json")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a manifest added with publications")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert any(
        f.startswith("data/sources/other/sources.json: a pull request that adds publications")
        for f in found
    ), found


def test_other_manifest_changes_are_not_drawn_list_changes(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    _change_manifest(repo, _retitle)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "publication and a retitled document")
    assert (
        problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
        == []
    )


def test_a_drawn_list_may_change_without_publications(repo: Path) -> None:
    _change_manifest(repo, _edit_a_drawn_text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a drawn list on its own")
    assert problems(repo, base="main", pull_request=True, clock=lambda: START) == []


def test_a_manifest_that_cannot_be_compared_is_refused_with_publications(repo: Path) -> None:
    _second(repo, Clock(START + timedelta(minutes=30)))
    (repo / ESKOM_MANIFEST).write_text('{"documents": 1}\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a broken manifest")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        f"{ESKOM_MANIFEST}: cannot compare its drawn lists; change it in its own pull request"
    ) in found


def test_a_symlinked_manifest_folder_is_refused_with_publications(repo: Path) -> None:
    """The loader's glob would read a manifest through the link; git shows only the link."""
    _second(repo, Clock(START + timedelta(minutes=30)))
    shutil.move(repo / "data/sources/eskom", repo / "data/elsewhere")
    _change_manifest_at(repo / "data/elsewhere/sources.json", _edit_a_drawn_text)
    (repo / "data/sources/eskom").symlink_to("../elsewhere")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a linked manifest folder")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert (
        "data/sources/eskom: a symbolic link or submodule under data/sources; change it in its"
        " own pull request"
    ) in found


def test_a_recorded_drawn_count_that_differs_from_the_rerun_is_refused(repo: Path) -> None:
    _added(repo)
    path = repo / FOLDER / "2026-07-01.r2.json"
    body = json.loads(path.read_text("utf-8"))
    body["publication"]["checks"]["citation_check"] = {
        "passed": 0,
        "no_text_layer": 15,
        "drawn": 1,
        "failed": 0,
    }
    path.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "commit", "-qam", "a claimed drawn value")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        f"{TARIFF}/2026-07-01/r2: the recorded citation check {{'passed': 0, 'no_text_layer': 15,"
        " 'drawn': 1, 'failed': 0} differs from this run's {'passed': 0, 'no_text_layer': 16,"
        " 'drawn': 0, 'failed': 0}"
    ]


def test_an_unknown_label_on_the_base_gets_no_drawn_count_message(repo: Path) -> None:
    """Only labels 2 and 3 have a drawn-count shape; any other label is refused on an added
    file (`test_a_changed_tool_label_is_refused`), and files on the base cannot change."""
    _counts_and_label(repo / FOLDER / "2026-07-01.r1.json", "hand made", drawn=False)
    assert problems(repo) == []
