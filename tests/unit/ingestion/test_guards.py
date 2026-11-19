"""The publication guards (P2-9): each check shown to fail on a deliberate violation.

Each test builds a throwaway git repository holding a copy of the data, publishes into it
with the real publish step (and a stand-in citation checker), and then breaks one rule.
The module is `slow` (git and file copies): `poe verify` and CI run it, `poe check` does not.
"""

import json
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion import guards
from munisense.ingestion.citation_check import CitationResult, Outcome, iter_cited
from munisense.ingestion.publish import Checker, Request, publish
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file, write_file
from munisense.provenance.sources import SourceDocument

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose main branch holds Tariff B r1 and the VAT rate r1."""
    for part in ("catalogue", "drafts"):
        shutil.copytree(ROOT / "data" / part, tmp_path / "data" / part)
    shutil.copytree(
        ROOT / "data" / "sources",
        tmp_path / "data" / "sources",
        ignore=shutil.ignore_patterns("*.pdf"),
    )
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
            ROOT / "data/drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json",
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
    assert problems(repo) == [
        f"{TARIFF}/2026-07-01/r2 is not recorded later than {TARIFF}/2026-07-01/r1,"
        " which it supersedes"
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
        "failed": 0,
    }
    path.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "commit", "-qam", "claimed checks")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert found == [
        f"{TARIFF}/2026-07-01/r2: the recorded citation check {{'passed': 16, 'no_text_layer': 0,"
        " 'failed': 0} differs from this run's {'passed': 0, 'no_text_layer': 16, 'failed': 0}"
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


def test_an_added_withdrawal_must_record_zero_counts(repo: Path) -> None:
    second = _second(repo, Clock(START + timedelta(minutes=30)), withdraw=True)
    body = json.loads(second.read_text("utf-8"))
    body["publication"]["checks"]["citation_check"]["passed"] = 3
    second.write_text(canonical.dumps(body), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "withdrawal")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START + timedelta(hours=1))
    assert any(
        "differs from this run's {'passed': 0, 'no_text_layer': 0, 'failed': 0}" in p for p in found
    ), found


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


def test_an_added_file_that_is_not_a_publication_is_refused_once(repo: Path) -> None:
    (repo / FOLDER / "notes.json").write_text("{}", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "stray file")
    found = problems(repo, base="main", pull_request=True, clock=lambda: START)
    assert found == [
        "tariffs/city-of-ekurhuleni/b-residential-1-phase/notes.json: not a publication"
        " (only <date>.r<N>.json files belong here)"
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
