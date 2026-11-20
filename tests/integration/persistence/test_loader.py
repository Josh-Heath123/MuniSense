"""The loader and `poe db-rebuild` (P2-11, ADR-0012 section 6).

Each test rebuilds the test database from a copy of the data in a temporary folder, with
publications made by the real publish step and a stand-in citation checker.
"""

import json
import os
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, text

from munisense.domain.tariffs import TariffVersion
from munisense.ingestion.guards import Loaded, load_all
from munisense.persistence import loader
from munisense.persistence.loader import LoadError, rebuild
from munisense.provenance import canonical
from munisense.provenance.drafts import load_file
from support.database import TestDatabase, dump
from support.publishing import (
    R1,
    ROOT,
    TARIFF,
    draft_b1,
    publish_all,
    publish_one,
    replace_draft,
)

DRAFT_B1 = ROOT / "data/drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json"


def _rows(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def test_two_rebuilds_give_identical_tables(
    data: Path, test_database: TestDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second rebuild reads a copy at another path, in reverse file order; the rows must
    not change. The dump pins its own time zone (shown by dumping under another one)."""
    publish_all(data)
    summary = rebuild(data, test_database.migration)
    first = dump(test_database.migration)
    elsewhere = tmp_path / "elsewhere" / "data"
    shutil.copytree(data, elsewhere, copy_function=os.link)
    real = load_all

    def reversed_load_all(where: Path) -> tuple[list[object], list[str]]:
        loaded, problems = real(where)
        return list(reversed(loaded)), problems

    monkeypatch.setattr(loader, "load_all", reversed_load_all)
    rebuild(elsewhere, test_database.migration)
    assert dump(test_database.migration) == first
    johannesburg = dump(test_database.migration, "Africa/Johannesburg")
    assert johannesburg != first  # the rendering differs ...
    assert dump(test_database.migration) == first  # ... the stored instants do not
    counts = (summary.publications, summary.tariff_versions, summary.vat_rates, summary.documents)
    assert counts == (3, 2, 1, 3)
    assert {table: len(rows) for table, rows in first.items()} == {
        "tariff_component": 4,
        "tariff_version": 2,
        "vat_rate": 1,
        "publication": 3,
        "tariff": 2,
        "customer_class": 1,
        "source_document": 3,
        "supplier": 1,
    }


def test_rows_hold_what_the_files_say(
    data: Path, test_database: TestDatabase, app_engine: Engine
) -> None:
    publish_all(data)
    rebuild(data, test_database.migration)
    ((payload, status, valid, recorded),) = _rows(
        app_engine,
        "SELECT payload, status, valid_period::text, recorded_during::text FROM tariff_version"
        " WHERE publication_id = 'city-of-ekurhuleni/b-residential-1-phase/2026-07-01/r1'",
    )
    assert TariffVersion.model_validate_json(json.dumps(payload)) == load_file(
        DRAFT_B1, TariffVersion
    )
    assert status == "estimated"
    assert valid == "[2026-07-01,2027-07-01)"
    assert isinstance(recorded, str)
    assert recorded.endswith(",)")
    components = _rows(
        app_engine,
        "SELECT c.position, c.name, c.kind FROM tariff_component c JOIN tariff_version v"
        " ON v.id = c.tariff_version_id"
        " WHERE v.publication_id = 'city-of-ekurhuleni/b-residential-1-phase/2026-07-01/r1'"
        " ORDER BY 1",
    )
    assert components == [(0, "basic", "fixed_charge"), (1, "energy", "seasonal_energy")]
    ((country, vat_valid),) = _rows(app_engine, "SELECT country, valid_period::text FROM vat_rate")
    assert (country, vat_valid) == ("south-africa", "[2018-04-01,)")


def _record_times(engine: Engine) -> dict[str, tuple[object, ...]]:
    """Each publication of tariff B1: its published_at and its version's record bounds."""
    rows = _rows(
        engine,
        "SELECT p.id, p.published_at, lower(v.recorded_during), upper(v.recorded_during)"
        " FROM publication p LEFT JOIN tariff_version v ON v.publication_id = p.id"
        " WHERE p.scope = 'city-of-ekurhuleni' AND p.code = 'b-residential-1-phase'",
    )
    return {str(row[0]): row[1:] for row in rows}


def test_a_correction_and_a_withdrawal_close_record_time(
    data: Path, test_database: TestDatabase, app_engine: Engine
) -> None:
    clock = publish_all(data)
    replace_draft(data, load_file(DRAFT_B1, TariffVersion))
    publish_one(data, clock, draft=draft_b1(data), supersedes=R1)
    publish_one(data, clock, withdraw=f"{TARIFF}/2026-07-01/r2")
    rebuild(data, test_database.migration)
    times = _record_times(app_engine)
    r1, r2, r3 = (times[f"{TARIFF}/2026-07-01/r{n}"] for n in (1, 2, 3))
    assert r1 == (r1[0], r1[0], r2[0])  # from its publication until r2's
    assert r2 == (r2[0], r2[0], r3[0])  # from its publication until the withdrawal's
    assert r3 == (r3[0], None, None)  # a withdrawal has no version row


def test_a_restore_after_a_withdrawal_is_open(
    data: Path, test_database: TestDatabase, app_engine: Engine
) -> None:
    clock = publish_all(data)
    publish_one(data, clock, withdraw=R1)
    replace_draft(data, load_file(DRAFT_B1, TariffVersion))
    publish_one(data, clock, draft=draft_b1(data))
    rebuild(data, test_database.migration)
    times = _record_times(app_engine)
    r1, r2, r3 = (times[f"{TARIFF}/2026-07-01/r{n}"] for n in (1, 2, 3))
    assert r1 == (r1[0], r1[0], r2[0])  # closed by the withdrawal
    assert r3 == (r3[0], r3[0], None)  # the restore supersedes nothing: open


@pytest.mark.parametrize("name", ["munisense", "munisense_testing", "dev_copy", "test"])
def test_only_dev_and_test_databases_are_rebuilt(
    data: Path, test_database: TestDatabase, name: str
) -> None:
    production = replace(test_database.migration, database=name)
    with pytest.raises(LoadError, match="must end in '_dev' or '_test'"):
        rebuild(data, production)


def test_a_bad_file_aborts_before_the_database_is_touched(
    data: Path, test_database: TestDatabase
) -> None:
    publish_all(data)
    rebuild(data, test_database.migration)
    before = dump(test_database.migration)
    path = data / "tariffs" / TARIFF / "2026-07-01.r1.json"
    path.write_bytes(path.read_bytes().removesuffix(b"\n"))
    with pytest.raises(LoadError, match="CanonicalJsonError"):
        rebuild(data, test_database.migration)
    assert dump(test_database.migration) == before


def test_a_database_refusal_rolls_the_whole_load_back(
    data: Path, test_database: TestDatabase
) -> None:
    """Two current versions of one tariff overlap: only the database sees it."""
    publish_all(data)
    rebuild(data, test_database.migration)
    before = dump(test_database.migration)
    folder = data / "tariffs" / TARIFF
    body = json.loads((folder / "2026-07-01.r1.json").read_text("utf-8"))
    version = TariffVersion.model_validate_json(json.dumps(body["version"]))
    start = version.effective_from.model_copy(update={"value": date(2026, 8, 1)})
    body["version"] = canonical.parse(
        version.model_copy(update={"effective_from": start}).model_dump_json()
    )
    body["publication"]["id"] = f"{TARIFF}/2026-08-01/r1"
    body["publication"]["published_at"] = "2026-12-01T10:00:00+00:00"
    (folder / "2026-08-01.r1.json").write_text(canonical.dumps(body), encoding="utf-8")
    with pytest.raises(LoadError, match="tariff_version_no_overlap"):
        rebuild(data, test_database.migration)
    assert dump(test_database.migration) == before


def _gap(data: Path) -> None:
    """r1 renamed to r2, id and path together: under its date, r1 is missing."""
    old = data / "tariffs" / TARIFF / "2026-07-01.r1.json"
    body = json.loads(old.read_text("utf-8"))
    body["publication"]["id"] = f"{TARIFF}/2026-07-01/r2"
    old.unlink()
    (old.parent / "2026-07-01.r2.json").write_text(canonical.dumps(body), encoding="utf-8")


def _manifest(data: Path, change: str) -> None:
    """Drop the VAT guide from the SARS manifest, or list it in a second manifest too."""
    path = data / "sources/sars/sources.json"
    body = json.loads(path.read_text("utf-8"))
    guide = next(d for d in body["documents"] if d["file"].startswith("vat-404"))
    if change == "unlisted":
        body["documents"].remove(guide)
        path.unlink()
        path.write_text(canonical.dumps(body), encoding="utf-8")
        return
    other = data / "sources/ekurhuleni/sources.json"
    second = json.loads(other.read_text("utf-8"))
    second["documents"].append(guide)
    other.unlink()
    other.write_text(canonical.dumps(second), encoding="utf-8")


def _edit_r1(data: Path, change: str) -> None:
    """Change r1's record in place (replacing the file, never writing through a link)."""
    path = data / "tariffs" / TARIFF / "2026-07-01.r1.json"
    body = json.loads(path.read_text("utf-8"))
    if change == "path":
        body["publication"]["id"] = f"{TARIFF}/2026-07-01/r7"
    else:
        body["publication"]["supersedes"] = f"{TARIFF}/2025-07-01/r1"
    path.unlink()
    path.write_text(canonical.dumps(body), encoding="utf-8")


@pytest.mark.parametrize(
    "change", ["hash", "missing", "class", "gap", "path", "supersedes", "unlisted", "twice"]
)
def test_refusals_found_in_the_files(data: Path, test_database: TestDatabase, change: str) -> None:
    clock = publish_all(data)
    pdf = data / "sources/sars/vat-404-guide-for-vendors-2025-01.pdf"
    messages = {
        "hash": "SHA-256 differs from the manifest",
        "missing": "listed but missing",
        "class": "one tariff keeps one customer class, not business, residential",
        "gap": "revisions are not r1 to r2 without gaps",
        "path": "its path says .*/r1, but its id is .*/r7",
        "supersedes": "supersedes .*/2025-07-01/r1, which does not exist",
        "unlisted": "vat/south-africa/2018-04-01/r1: .* cites document 9204c3f8.*,"
        " which no source manifest lists",
        "twice": "document 9204c3f8.* is listed in two manifests",
    }
    if change in {"hash", "missing"}:
        pdf.unlink()
        if change == "hash":
            pdf.write_bytes(b"not the guide")
    elif change == "class":
        version = load_file(DRAFT_B1, TariffVersion)
        replace_draft(data, version.model_copy(update={"customer_class": "business"}))
        publish_one(data, clock, draft=draft_b1(data), supersedes=R1)
    elif change == "gap":
        _gap(data)
    elif change in {"unlisted", "twice"}:
        _manifest(data, change)
    else:
        _edit_r1(data, change)
    with pytest.raises(LoadError, match=messages[change]):
        rebuild(data, test_database.migration)


def test_the_command_rebuilds_and_reports(
    data: Path,
    test_database: TestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publish_all(data)
    monkeypatch.chdir(data.parent)
    env = {"MUNISENSE_MIGRATION_DATABASE_URL": test_database.migration.url}
    assert loader.main([], env) == 0
    out = capsys.readouterr().out
    assert "munisense_test rebuilt: 3 publications (2 tariff versions, 1 VAT rates)" in out
    assert "3 source documents" in out
    broken = data / "tariffs" / TARIFF / "2026-07-01.r1.json"
    broken.unlink()
    broken.write_text("{}", encoding="utf-8")
    assert loader.main([], env) == 1
    assert "db-rebuild refused:" in capsys.readouterr().err
    assert loader.main([], {"PGHOST": "x"}) == 2
    assert "PGHOST is set" in capsys.readouterr().err
    assert loader.main(["--force"], env) == 2
    assert "takes no arguments" in capsys.readouterr().err


def test_an_unreadable_manifest_is_refused(data: Path, test_database: TestDatabase) -> None:
    manifest = data / "sources/sars/sources.json"
    manifest.unlink()
    manifest.write_text(canonical.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(
        LoadError, match=r"^ValidationError: \d+ validation errors? for SourceManifest"
    ):
        rebuild(data, test_database.migration)


def test_a_schema_with_other_tables_is_refused(
    data: Path, test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A table the loader does not know would keep stale rows: refuse instead."""
    monkeypatch.setattr(loader, "TABLES", loader.TABLES[1:])
    with pytest.raises(LoadError, match="differ from the loader's"):
        rebuild(data, test_database.migration)


BREAKS = {
    "has no version row": ["DELETE FROM vat_rate"],
    "has record time that does not start at its published_at": [
        "UPDATE vat_rate SET recorded_during ="
        " tstzrange(lower(recorded_during) + interval '1 second', NULL)"
    ],
    "has a version of another tariff": ["UPDATE tariff SET tariff_code = tariff_code || '-x'"],
    "has a VAT rate of another country": ["UPDATE vat_rate SET country = 'elsewhere'"],
}


@pytest.mark.parametrize("rule", list(BREAKS))
def test_the_loaded_rows_are_checked(
    data: Path, test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    """Each row check finds its rule broken inside the load, and the load rolls back."""
    publish_all(data)
    rebuild(data, test_database.migration)
    before = dump(test_database.migration)
    real = loader._load

    def broken(connection: Connection, where: Path, loaded: list[Loaded]) -> loader.Summary:
        summary = real(connection, where, loaded)
        for sql in BREAKS[rule]:
            connection.execute(text(sql))
        return summary

    monkeypatch.setattr(loader, "_load", broken)
    with pytest.raises(LoadError) as refused:
        rebuild(data, test_database.migration)
    assert refused.value.problems
    assert all(problem.endswith(rule) for problem in refused.value.problems)
    assert dump(test_database.migration) == before
