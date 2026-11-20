"""The publish step (P2-8, ADR-0012 sections 3, 5 and 7).

Every test works on a copy of the data in a temporary directory, never on `data/`. Most
use a stand-in citation checker so they need no child process; the end-to-end tests at the
bottom use the real one. The whole module is `slow` (each test copies the data, about 0.4 s):
`poe verify` and CI run it, `poe check` does not (E43, W19).
"""

import json
import os
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from munisense.domain.citations import TextCheck, Verified
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion import publish as publish_module
from munisense.ingestion.citation_check import CitationResult, Outcome, iter_cited
from munisense.ingestion.publish import PublishRefusedError, Request, publish
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file, write_file
from munisense.provenance.errors import ProvenanceError
from munisense.provenance.publication import (
    CitationCheckCounts,
    PublishChecks,
    TariffPublication,
    VatRatePublication,
    load_bytes,
)
from munisense.provenance.sources import SourceDocument
from support.builders import fixture_free_basic
from support.publishing import DRAFTS

ROOT = Path(__file__).resolve().parents[3]
TARIFF = "city-of-ekurhuleni/b-residential-1-phase"
START = datetime(2026, 12, 1, 9, 30, tzinfo=UTC)
pytestmark = pytest.mark.slow


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A copy of the catalogue, the source manifests (not the PDFs) and the drafts.

    The stand-in checker reads no PDF; `with_pdfs` adds them for the end-to-end tests.
    """
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data" / "catalogue", target / "catalogue")
    shutil.copytree(DRAFTS, target / "drafts")
    shutil.copytree(
        ROOT / "data" / "sources", target / "sources", ignore=shutil.ignore_patterns("*.pdf")
    )
    return target


def with_pdfs(data: Path) -> Path:
    for pdf in (ROOT / "data" / "sources").glob("*/*.pdf"):
        shutil.copy(pdf, data / "sources" / pdf.parent.name / pdf.name)
    return data


class Clock:
    """Each call is one minute after the last."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def checker(failed: tuple[str, ...] = ()) -> publish_module.Checker:
    """A stand-in: VAT citations pass, tariff citations have no text layer."""

    def check(
        model: BaseModel, _documents: dict[str, tuple[Path, SourceDocument]]
    ) -> list[CitationResult]:
        ok = Outcome.PASSED if isinstance(model, VatRate) else Outcome.NO_TEXT_LAYER
        return [
            CitationResult(
                path,
                cited.citation.page,
                Outcome.FAILED if path in failed else ok,
                "stand-in failure" if path in failed else "stand-in",
            )
            for path, cited in iter_cited(model)
        ]

    return check


def tariff_draft(data: Path) -> Path:
    return data / "drafts" / "city-of-ekurhuleni" / "2026-27" / "b-residential-1-phase.json"


def vat_draft(data: Path) -> Path:
    return data / "drafts" / "vat" / "south-africa" / "2018-04-01.json"


def _publish(data: Path, clock: Clock | None = None, **request: object) -> publish_module.Result:
    return publish(data, Request(reason="test", **request), clock or Clock(), checker())  # type: ignore[arg-type]


def _write_tariff(data: Path, version: TariffVersion) -> Path:
    path = tariff_draft(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_file(path, version)
    return path


def _dated(
    version: TariffVersion, start: date | None = None, end: date | None = None
) -> TariffVersion:
    updates: dict[str, object] = {}
    if start is not None:
        updates["effective_from"] = version.effective_from.model_copy(update={"value": start})
    if end is not None:
        assert version.effective_to is not None
        updates["effective_to"] = version.effective_to.model_copy(update={"value": end})
    return version.model_copy(update=updates)


@pytest.fixture
def original(data: Path) -> TariffVersion:
    return load_file(tariff_draft(data), TariffVersion)


def _tariff_file(data: Path, name: str) -> TariffPublication:
    return load_bytes((data / "tariffs" / TARIFF / name).read_bytes(), TariffPublication)


def _counts(checks: object) -> CitationCheckCounts:
    assert isinstance(checks, PublishChecks)
    return checks.citation_check


# --- first publications --------------------------------------------------------------


def test_a_vat_rate_is_published_with_its_record_time(data: Path) -> None:
    clock = Clock()
    result = _publish(data, clock, draft=vat_draft(data))
    path = data / "vat" / "south-africa" / "2018-04-01.r1.json"
    assert result.written
    assert result.target == path
    publication = load_bytes(path.read_bytes(), VatRatePublication)
    record = publication.publication
    assert (record.id, record.supersedes, record.published_at) == (
        "vat/south-africa/2018-04-01/r1",
        None,
        clock.now,
    )
    assert _counts(record.checks).passed == 2
    assert publication.version == load_file(DRAFTS / "vat/south-africa/2018-04-01.json", VatRate)
    assert not vat_draft(data).exists()
    canonical.check_bytes(path.read_bytes())


def test_a_tariff_is_published_at_its_path(data: Path, original: TariffVersion) -> None:
    _publish(data, draft=tariff_draft(data))
    publication = _tariff_file(data, "2026-07-01.r1.json")
    assert publication.version == original
    assert _counts(publication.publication.checks).no_text_layer == 16


def test_check_only_writes_nothing_and_keeps_the_draft(data: Path) -> None:
    result = _publish(data, draft=vat_draft(data), check_only=True)
    assert not result.written
    assert not result.target.exists()
    assert vat_draft(data).exists()


# --- refusals ------------------------------------------------------------------------


def _refused(data: Path, *, clock: Clock | None = None, **request: object) -> list[str]:
    with pytest.raises(PublishRefusedError) as refused:
        _publish(data, clock, **request)
    return refused.value.reasons


def test_a_citation_failure_refuses(data: Path) -> None:
    with pytest.raises(PublishRefusedError) as refused:
        publish(data, Request(reason="t", draft=vat_draft(data)), Clock(), checker(("percent",)))
    assert refused.value.reasons == ["citation percent (page 15): stand-in failure"]
    assert vat_draft(data).exists()


def test_a_verified_value_must_agree_with_the_computed_text_check(
    data: Path, original: TariffVersion
) -> None:
    status = Verified(
        verifier="owner",
        verifier_kind="human",
        method="visual comparison with the scanned page",
        verified_on=date(2026, 12, 1),
        text_check=TextCheck.PASSED,  # the page is a scan: the check gives no_text_layer
    )
    name = original.printed_name.model_copy(update={"status": status})
    _write_tariff(data, original.model_copy(update={"printed_name": name}))
    reasons = _refused(data, draft=tariff_draft(data))
    assert reasons == [
        "printed_name: verified with text check passed, but the citation check gives no_text_layer"
    ]


def test_a_draft_in_the_wrong_tariff_year_folder_refuses(data: Path) -> None:
    wrong = data / "drafts" / "city-of-ekurhuleni" / "2025-26" / "b-residential-1-phase.json"
    wrong.parent.mkdir()
    tariff_draft(data).rename(wrong)
    assert _refused(data, draft=wrong) == [
        "this draft belongs at drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json,"
        " not drafts/city-of-ekurhuleni/2025-26/b-residential-1-phase.json"
    ]


def test_a_misnamed_vat_draft_refuses(data: Path) -> None:
    wrong = vat_draft(data).with_name("2018-04-02.json")
    vat_draft(data).rename(wrong)
    assert "a VAT draft sits at" in _refused(data, draft=wrong)[0]


def test_a_supplier_not_in_the_catalogue_refuses(data: Path) -> None:
    path = data / "catalogue" / "suppliers.json"
    body = json.loads(path.read_text("utf-8"))
    body["suppliers"][0]["code"] = "elsewhere"
    path.write_text(canonical.dumps(body), encoding="utf-8")
    assert _refused(data, draft=tariff_draft(data)) == [
        "supplier city-of-ekurhuleni is not in the catalogue"
    ]


def test_a_file_that_is_not_a_publication_in_the_folder_refuses(data: Path) -> None:
    target = data / "vat" / "south-africa" / "2018-04-01.r1.json"
    target.parent.mkdir(parents=True)
    shutil.copy(DRAFTS / "vat/south-africa/2018-04-01.json", target)
    with pytest.raises(ProvenanceError):  # not a publication: refused while reading
        _publish(data, draft=vat_draft(data))


def test_an_empty_reason_is_refused_as_invalid(data: Path) -> None:
    with pytest.raises(PublishRefusedError, match="the publication is not valid"):
        publish(data, Request(reason="", draft=vat_draft(data)), Clock(), checker())


def test_a_clock_without_an_offset_refuses(data: Path) -> None:
    def naive() -> datetime:
        return datetime(2026, 12, 1, 9, 30)  # noqa: DTZ001  # the point of the test

    with pytest.raises(PublishRefusedError, match="without an offset"):
        publish(data, Request(reason="t", draft=vat_draft(data)), naive, checker())


def test_nothing_to_publish_refuses(data: Path) -> None:
    assert _refused(data) == ["give a draft to publish, or --withdraw <id>"]


# --- corrections, withdrawals and amendments -----------------------------------------


def test_a_correction_supersedes_the_revision_before_it(
    data: Path, original: TariffVersion
) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    result = _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    assert result.publication_id == f"{TARIFF}/2026-07-01/r2"
    second = _tariff_file(data, "2026-07-01.r2.json").publication
    assert second.supersedes == f"{TARIFF}/2026-07-01/r1"
    assert second.published_at > _tariff_file(data, "2026-07-01.r1.json").publication.published_at


def test_a_correction_may_move_its_effective_date(data: Path, original: TariffVersion) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, _dated(original, start=date(2026, 8, 1)))
    result = _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    assert result.target.name == "2026-08-01.r1.json"  # ADR-0013: next free under its date


def test_an_overlapping_version_must_supersede(data: Path, original: TariffVersion) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    reasons = _refused(data, clock=clock, draft=tariff_draft(data))
    assert reasons == [f"overlaps {TARIFF}/2026-07-01/r1 in valid time without superseding it"]


@pytest.mark.parametrize(
    ("supersedes", "message"),
    [
        (f"{TARIFF}/2026-07-01/r5", "is not a publication of this tariff"),
        (
            "city-of-ekurhuleni/b-residential-3-phase/2026-07-01/r1",
            "is not a publication of this tariff",
        ),
    ],
)
def test_superseding_something_that_is_not_there_refuses(
    data: Path, original: TariffVersion, supersedes: str, message: str
) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    assert (
        message in _refused(data, clock=clock, draft=tariff_draft(data), supersedes=supersedes)[0]
    )


def test_a_publication_is_superseded_only_once(data: Path, original: TariffVersion) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    _write_tariff(data, original)
    reasons = _refused(
        data, clock=clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1"
    )
    assert f"{TARIFF}/2026-07-01/r1 is already superseded by {TARIFF}/2026-07-01/r2" in reasons


def test_a_withdrawal_holds_no_version_and_ends_the_version(data: Path) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    result = _publish(data, clock, withdraw=f"{TARIFF}/2026-07-01/r1")
    withdrawal = _tariff_file(data, "2026-07-01.r2.json")
    assert result.publication_id == f"{TARIFF}/2026-07-01/r2"
    assert withdrawal.version is None
    assert withdrawal.publication.checks.model_dump() == {
        "kind": "withdrawal",
        "tool_version": "munisense publish 2",
        "withdrawn": "exists and is current",
    }


def test_a_withdrawal_cannot_be_superseded_and_a_restore_takes_the_next_free_revision(
    data: Path, original: TariffVersion
) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _publish(data, clock, withdraw=f"{TARIFF}/2026-07-01/r1")
    _write_tariff(data, original)
    reasons = _refused(
        data, clock=clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r2"
    )
    assert reasons == [
        f"{TARIFF}/2026-07-01/r2 is a withdrawal; republish with no supersedes instead"
    ]
    restored = _publish(data, clock, draft=tariff_draft(data))
    assert restored.publication_id == f"{TARIFF}/2026-07-01/r3"
    assert _tariff_file(data, "2026-07-01.r3.json").publication.supersedes is None


def test_a_mid_year_amendment_publishes_the_shortening_revision_first(
    data: Path, original: TariffVersion
) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    new = _dated(original, start=date(2027, 2, 1))
    _write_tariff(data, new)
    wrong_order = _refused(data, clock=clock, draft=tariff_draft(data))
    assert wrong_order == [f"overlaps {TARIFF}/2026-07-01/r1 in valid time without superseding it"]
    _write_tariff(data, _dated(original, end=date(2027, 2, 1)))
    _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    _write_tariff(data, new)
    result = _publish(data, clock, draft=tariff_draft(data))
    assert result.publication_id == f"{TARIFF}/2027-02-01/r1"


def test_record_time_must_be_later_than_what_is_superseded(
    data: Path, original: TariffVersion
) -> None:
    _publish(data, Clock(), draft=tariff_draft(data))
    _write_tariff(data, original)
    earlier = Clock(START - timedelta(days=1))
    reasons = _refused(
        data, clock=earlier, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1"
    )
    assert reasons == [f"the record time is not later than that of {TARIFF}/2026-07-01/r1"]


def test_a_publication_file_whose_name_disagrees_with_its_id_is_refused(data: Path) -> None:
    _publish(data, draft=tariff_draft(data))
    folder = data / "tariffs" / TARIFF
    (folder / "2026-07-01.r1.json").rename(folder / "2026-07-01.r9.json")
    _write_tariff(
        data,
        load_file(
            DRAFTS / "city-of-ekurhuleni/2026-27/b-residential-1-phase.json",
            TariffVersion,
        ),
    )
    with pytest.raises(ProvenanceError, match="does not match its id"):
        _publish(data, draft=tariff_draft(data))


# --- the command ----------------------------------------------------------------------


def test_the_command_reports_what_it_would_publish(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = publish_module.main(
        [str(vat_draft(data)), "--reason", "dry run", "--check"], data, Clock(), checker()
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("would publish vat/south-africa/2018-04-01/r1")
    assert "passed        percent (page 15)" in out


def test_the_command_lists_refusals(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = publish_module.main(
        [str(vat_draft(data)), "--reason", "x"], data, Clock(), checker(("percent",))
    )
    assert code == 1
    assert "refused:\n  - citation percent (page 15): stand-in failure" in capsys.readouterr().err


def test_the_command_reports_an_unreadable_draft(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vat_draft(data).write_text('{"x": 1}', encoding="utf-8")
    assert publish_module.main([str(vat_draft(data)), "--reason", "x"], data) == 1
    assert capsys.readouterr().err.startswith("refused: CanonicalJsonError")


@pytest.mark.parametrize(
    "argv",
    [
        ["--reason", "x"],
        ["draft.json", "--withdraw", "a/b/2026-07-01/r1", "--reason", "x"],
        ["--withdraw", "a/b/2026-07-01/r1", "--supersedes", "a/b/2026-07-01/r1", "--reason", "x"],
    ],
)
def test_the_command_needs_exactly_one_thing_to_publish(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        publish_module.main(argv)
    assert exited.value.code == 2


def test_the_data_folder_defaults_to_data_under_the_working_directory(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(data.parent)
    code = publish_module.main(
        ["--withdraw", f"{TARIFF}/2026-07-01/r1", "--reason", "x"], None, Clock(), checker()
    )
    assert code == 1
    assert "is not a publication of this tariff" in capsys.readouterr().err


def test_the_command_reports_a_draft_it_could_not_remove(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_unlink = Path.unlink

    def refuse(self: Path, missing_ok: bool = False) -> None:
        if self.suffix == ".json" and "drafts" in self.parts:
            raise PermissionError(self.name)
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)
    code = publish_module.main([str(vat_draft(data)), "--reason", "x"], data, Clock(), checker())
    assert code == 3
    assert "published, but could not remove the draft: PermissionError" in capsys.readouterr().err
    assert (data / "vat/south-africa/2018-04-01.r1.json").exists()


# --- more refusals (P2-8 review) ------------------------------------------------------


def test_a_moved_correction_under_a_date_with_revisions_takes_the_next_free_one(
    data: Path, original: TariffVersion
) -> None:
    """The ADR-0012 deadlock, now publishable (ADR-0013): D has r1 and r2 already."""
    clock = Clock()
    later = _dated(original, start=date(2027, 1, 1))
    _write_tariff(data, later)
    _publish(data, clock, draft=tariff_draft(data))  # D/r1, D = 2027-01-01
    _publish(data, clock, withdraw=f"{TARIFF}/2027-01-01/r1")  # D/r2
    _write_tariff(data, _dated(original, end=date(2027, 1, 1)))
    _publish(data, clock, draft=tariff_draft(data))  # C/r1, C = 2026-07-01
    _write_tariff(data, later)
    result = _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    assert result.publication_id == f"{TARIFF}/2027-01-01/r3"
    assert _tariff_file(data, "2027-01-01.r3.json").publication.supersedes == (
        f"{TARIFF}/2026-07-01/r1"
    )


def test_an_existing_target_path_refuses_and_nothing_is_overwritten(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: a numbering race. The next free revision is forced to one that exists."""
    clock = Clock()
    _publish(data, clock, draft=vat_draft(data))
    before = (data / "vat/south-africa/2018-04-01.r1.json").read_bytes()
    monkeypatch.setattr(publish_module, "_next_revision", lambda *_: 1)
    reasons = _refused(data, clock=clock, withdraw="vat/south-africa/2018-04-01/r1")
    assert reasons == ["2018-04-01.r1.json already exists"]
    assert (data / "vat/south-africa/2018-04-01.r1.json").read_bytes() == before


def test_a_withdrawal_cannot_be_withdrawn(data: Path) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _publish(data, clock, withdraw=f"{TARIFF}/2026-07-01/r1")
    reasons = _refused(data, clock=clock, withdraw=f"{TARIFF}/2026-07-01/r2")
    assert (
        f"{TARIFF}/2026-07-01/r2 is a withdrawal; republish with no supersedes instead" in reasons
    )


def test_a_superseded_publication_cannot_be_withdrawn(data: Path, original: TariffVersion) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    reasons = _refused(data, clock=clock, withdraw=f"{TARIFF}/2026-07-01/r1")
    assert f"{TARIFF}/2026-07-01/r1 is already superseded by {TARIFF}/2026-07-01/r2" in reasons


def test_a_withdrawal_needs_a_later_record_time(data: Path) -> None:
    _publish(data, Clock(), draft=tariff_draft(data))
    earlier = Clock(START - timedelta(hours=1))
    reasons = _refused(data, clock=earlier, withdraw=f"{TARIFF}/2026-07-01/r1")
    assert reasons == [f"the record time is not later than that of {TARIFF}/2026-07-01/r1"]


def test_an_equal_record_time_is_refused(data: Path, original: TariffVersion) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, original)
    same = Clock(clock.now - timedelta(minutes=1))  # its next call returns clock.now again
    reasons = _refused(
        data, clock=same, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1"
    )
    assert reasons == [f"the record time is not later than that of {TARIFF}/2026-07-01/r1"]


def test_record_time_never_goes_back_within_a_tariff(data: Path, original: TariffVersion) -> None:
    """A clock that steps back between the two halves of a mid-year amendment is refused."""
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    _write_tariff(data, _dated(original, end=date(2027, 2, 1)))
    _publish(data, clock, draft=tariff_draft(data), supersedes=f"{TARIFF}/2026-07-01/r1")
    _write_tariff(data, _dated(original, start=date(2027, 2, 1)))
    reasons = _refused(data, clock=Clock(START), draft=tariff_draft(data))
    assert reasons == [f"the record time is not later than that of {TARIFF}/2026-07-01/r2"]


def _vat_rate(data: Path, start: date, end: date | None) -> Path:
    rate = load_file(DRAFTS / "vat/south-africa/2018-04-01.json", VatRate)
    start_cited = rate.start_cited.model_copy(update={"value": start})
    end_cited = None if end is None else rate.start_cited.model_copy(update={"value": end})
    path = data / "drafts" / "vat" / "south-africa" / f"{start.isoformat()}.json"
    write_file(path, rate.model_copy(update={"start_cited": start_cited, "end_cited": end_cited}))
    return path


def test_two_open_ended_vat_rates_overlap(data: Path) -> None:
    clock = Clock()
    _publish(data, clock, draft=vat_draft(data))
    later = _vat_rate(data, date(2027, 1, 1), None)
    assert _refused(data, clock=clock, draft=later) == [
        "overlaps vat/south-africa/2018-04-01/r1 in valid time without superseding it"
    ]


def test_an_open_ended_vat_rate_follows_one_that_ends_on_its_start(data: Path) -> None:
    clock = Clock()
    _publish(data, clock, draft=vat_draft(data))
    shortened = _vat_rate(data, date(2018, 4, 1), date(2027, 1, 1))
    _publish(data, clock, draft=shortened, supersedes="vat/south-africa/2018-04-01/r1")
    later = _vat_rate(data, date(2027, 1, 1), None)
    assert _publish(data, clock, draft=later).publication_id == "vat/south-africa/2027-01-01/r1"


def test_an_earlier_version_may_end_where_a_later_one_starts(
    data: Path, original: TariffVersion
) -> None:
    clock = Clock()
    _publish(data, clock, draft=tariff_draft(data))
    earlier = _dated(original, start=date(2025, 7, 1), end=date(2026, 7, 1))
    path = data / "drafts" / "city-of-ekurhuleni" / "2025-26" / "b-residential-1-phase.json"
    path.parent.mkdir()
    write_file(path, earlier)
    assert _publish(data, clock, draft=path).publication_id == f"{TARIFF}/2025-07-01/r1"


def test_a_canonical_but_invalid_draft_is_refused(data: Path) -> None:
    body = json.loads(vat_draft(data).read_text("utf-8"))
    body["percent"]["value"] = "fifteen"
    vat_draft(data).write_text(canonical.dumps(body), encoding="utf-8")
    reasons = _refused(data, draft=vat_draft(data))
    assert reasons
    assert all(r.startswith("the draft is not valid: percent.value:") for r in reasons)


@pytest.mark.parametrize("where", ["outside", "folder"])
def test_a_path_that_is_not_a_draft_file_is_refused(data: Path, tmp_path: Path, where: str) -> None:
    path = tmp_path / "elsewhere.json" if where == "outside" else data / "drafts"
    if where == "outside":
        shutil.copy(vat_draft(data), path)
    assert _refused(data, draft=path) == [f"{path} is not a draft file under {data / 'drafts'}"]


def test_an_invalid_handle_names_the_field(data: Path) -> None:
    request = Request(reason="t", published_by="Josh_Heath", draft=vat_draft(data))
    with pytest.raises(PublishRefusedError) as refused:
        publish(data, request, Clock(), checker())
    assert refused.value.reasons == [
        "the publication is not valid: publication.published_by: String should match pattern"
        " '^[a-z][a-z0-9_-]{1,39}$'"
    ]


def test_a_free_basic_allocation_cannot_be_published_before_td_10(
    data: Path, original: TariffVersion
) -> None:
    components = (*original.components, fixture_free_basic("50"))
    _write_tariff(data, original.model_copy(update={"components": components}))
    wrong = data / "drafts" / "city-of-ekurhuleni" / "2025-26" / "b-residential-1-phase.json"
    wrong.parent.mkdir()
    tariff_draft(data).rename(wrong)
    assert _refused(data, draft=wrong) == [  # every reason is listed, not only the first
        "a free basic allocation cannot be published until TD-10 is done (E49)",
        "this draft belongs at drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json,"
        " not drafts/city-of-ekurhuleni/2025-26/b-residential-1-phase.json",
    ]


def test_a_failed_write_leaves_no_file(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object) -> None:
        msg = "link failed"
        raise OSError(msg)

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError, match="link failed"):
        _publish(data, draft=vat_draft(data))
    assert not list((data / "vat" / "south-africa").iterdir())
    assert vat_draft(data).exists()


def test_a_document_listed_twice_is_refused(data: Path) -> None:
    shutil.copy(data / "sources/sars/sources.json", data / "sources/ekurhuleni/sources.json")
    with pytest.raises(ProvenanceError, match="listed in two manifests"):
        _publish(data, draft=vat_draft(data))


# --- end to end, with the real citation check -----------------------------------------


def test_a_hash_mismatch_is_refused_end_to_end(data: Path) -> None:
    with_pdfs(data)
    pdf = data / "sources/sars/vat-404-guide-for-vendors-2025-01.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"\n")
    with pytest.raises(PublishRefusedError, match="is not the listed document"):
        publish(data, Request(reason="t", draft=vat_draft(data)), Clock())


def test_an_unlisted_document_is_refused_end_to_end(data: Path) -> None:
    with_pdfs(data)
    (data / "sources/sars/sources.json").unlink()
    with pytest.raises(PublishRefusedError, match="not in a source manifest"):
        publish(data, Request(reason="t", draft=vat_draft(data)), Clock())


def test_the_real_vat_draft_and_tariff_b_publish_end_to_end(data: Path) -> None:
    with_pdfs(data)
    clock = Clock()
    publish(data, Request(reason="t", draft=vat_draft(data)), clock)
    publish(data, Request(reason="t", draft=tariff_draft(data)), clock)
    vat = load_bytes(
        (data / "vat/south-africa/2018-04-01.r1.json").read_bytes(), VatRatePublication
    )
    assert _counts(vat.publication.checks).passed == 2
    tariff = _tariff_file(data, "2026-07-01.r1.json")
    assert _counts(tariff.publication.checks).no_text_layer == 16


def test_a_changed_printed_text_is_refused_end_to_end(data: Path) -> None:
    with_pdfs(data)
    rate = load_file(vat_draft(data), VatRate)
    citation = rate.percent.citation.model_copy(
        update={"printed_text": "at the standard rate of 16%"}
    )
    write_file(
        vat_draft(data),
        rate.model_copy(update={"percent": rate.percent.model_copy(update={"citation": citation})}),
    )
    with pytest.raises(PublishRefusedError, match="printed text not found"):
        publish(data, Request(reason="t", draft=vat_draft(data)), Clock())


def test_the_default_clock_gives_an_offset() -> None:
    assert publish_module._now().utcoffset() is not None
