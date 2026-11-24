"""Storage for the time-of-use shapes (P4-12, ADR-0016 points 1, 3 and 6).

A made-up time-of-use version (a calendar with a holiday list, time-of-use energy, an
export credit with its cap, and a quantity charge limited to the high season) goes through the real
publish step, the publication guards and the loader, and is read back as the application
role. It must come back equal as JSON text and bill identically from the file and from the
database. Every value is a fixture marked "not real tariff data"; its citations are pointed
at a committed document only because the loader requires every cited document to be listed.
The citation checker is a stand-in that gives one calendar range `drawn`, so the recorded
`drawn` count is 1 and a lost or altered count would be caught. The Python entry points stand
in for the commands (`publish(check_only=True)` for `poe publish --check`, `rebuild` for
`poe db-rebuild`; their `main` wrappers are tested elsewhere).
"""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, text

from munisense.domain.billing import (
    BillingPeriod,
    CustomerQuantities,
    IntervalReading,
    IntervalReadings,
    TimeOfUseBuckets,
    calculate_bill,
)
from munisense.domain.citations import StatusKind, iter_cited
from munisense.domain.tariffs import DayType, ExportCap, TariffVersion, TouPeriod
from munisense.ingestion import guards
from munisense.ingestion.citation_check import CitationResult, Outcome
from munisense.ingestion.publish import Request, publish
from munisense.persistence.loader import rebuild
from munisense.persistence.repository import (
    CitedValue,
    tariff_version,
    values_citing,
    values_with_status,
    vat_table,
)
from munisense.provenance import canonical
from munisense.provenance.drafts import load_vat_table, write_file
from munisense.provenance.publication import PublishChecks, TariffPublication, load_bytes, render
from munisense.provenance.sources import SourceDocument
from support.builders import (
    FIXTURE_DOCUMENT,
    fixture_billing_policy,
    fixture_calendar,
    fixture_export_credit,
    fixture_holiday_list,
    fixture_quantity_charge,
    fixture_tou_energy,
    fixture_version,
)
from support.database import TestDatabase
from support.publishing import DRAFTS, Clock, checker

BOOK = "eef82b077d7df4dd7b157ce757e2e56368170cec3bb69614fd81042451a1be84"  # Eskom, committed
SUPPLIER, CODE = "eskom-direct", "fixture-tou"
LATER = datetime(2027, 1, 1, tzinfo=UTC)
SAST = timezone(timedelta(hours=2))
PUBLICATION = f"{SUPPLIER}/{CODE}/2026-07-01/r1"
DRAWN_PATH = "tou_calendar.schedules[0].ranges[0]"


def drawn_checker(
    model: BaseModel, sources: dict[str, tuple[Path, SourceDocument]]
) -> list[CitationResult]:
    """The stand-in, except that one calendar range is drawn."""
    return [
        CitationResult(r.path, r.page, Outcome.DRAWN, "stand-in") if r.path == DRAWN_PATH else r
        for r in checker(model, sources)
    ]


def _version() -> TariffVersion:
    holidays = fixture_holiday_list(
        (date(2026, 7, 1), date(2027, 7, 1)),
        (date(2026, 8, 10), DayType.SUNDAY),
        (date(2026, 12, 25), DayType.SUNDAY),
    )
    version = fixture_version(
        fixture_tou_energy(),
        fixture_export_credit(),
        fixture_quantity_charge(seasons=("high",)),
        tou_calendar=fixture_calendar(holidays=holidays),
        billing=fixture_billing_policy(export_cap=ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH),
        tariff_code=CODE,
    )
    text = version.model_dump_json().replace(FIXTURE_DOCUMENT, BOOK)
    text = text.replace('"supplier":"fixture-metro"', f'"supplier":"{SUPPLIER}"')
    return TariffVersion.model_validate_json(text)


def _draft(data: Path) -> Path:
    return data / "drafts" / SUPPLIER / "2026-27" / f"{CODE}.json"


@pytest.fixture
def published(data: Path) -> Path:
    """The VAT rate and the time-of-use version, published; returns the version's file."""
    draft = _draft(data)
    draft.parent.mkdir(parents=True)
    write_file(draft, _version())
    clock = Clock()
    vat = data / "drafts/vat/south-africa/2018-04-01.json"
    publish(data, Request(reason="t", draft=vat), clock, checker)
    assert not publish(
        data, Request(reason="t", draft=draft, check_only=True), clock, drawn_checker
    ).written
    publish(data, Request(reason="t", draft=draft), clock, drawn_checker)
    return data / "tariffs" / SUPPLIER / CODE / "2026-07-01.r1.json"


def _checks(path: Path) -> PublishChecks:
    checks = load_bytes(path.read_bytes(), TariffPublication).publication.checks
    assert isinstance(checks, PublishChecks)
    return checks


@pytest.fixture
def connection(app_engine: Engine) -> Iterator[Connection]:
    with app_engine.connect() as c:
        yield c


def test_the_publication_is_canonical_and_holds_every_new_shape(published: Path) -> None:
    data = published.read_bytes()
    publication = load_bytes(data, TariffPublication)
    assert render(publication).encode("utf-8") == data
    version = publication.version
    assert version is not None
    assert version == _version()
    kinds = [component.kind for component in version.components]
    assert kinds == ["time_of_use_energy", "export_credit", "quantity_charge"]
    assert version.billing_policy.export_cap is ExportCap.USE_IN_PERIOD_PER_CALENDAR_MONTH
    assert version.tou_calendar is not None
    assert version.tou_calendar.holidays.listed


def test_the_label_3_counts_record_the_drawn_value(published: Path) -> None:
    checks = _checks(published)
    assert checks.tool_version == "munisense publish 3"
    counts = checks.citation_check
    assert (counts.drawn, counts.failed) == (1, 0)
    assert counts.passed + counts.no_text_layer + (counts.drawn or 0) == len(
        list(iter_cited(_version()))
    )


def _added_problems(data: Path, published: Path) -> list[str]:
    loaded, problems = guards.load_all(data)
    assert problems == []
    added = [str(published.relative_to(data.parent))]
    now = load_bytes(published.read_bytes(), TariffPublication).publication.published_at
    return guards.check_added(data, loaded, added, now, drawn_checker)


def test_the_guards_pass_the_set_and_recheck_the_added_publication(
    published: Path, data: Path
) -> None:
    """The pull-request re-check: label, citation re-run over the calendar and the new
    components, recorded counts (the drawn count among them), Verified text checks."""
    assert guards.run_checks(data) == []
    assert _added_problems(data, published) == []


def test_the_recheck_refuses_an_altered_drawn_count(published: Path, data: Path) -> None:
    body = json.loads(published.read_text("utf-8"))
    body["publication"]["checks"]["citation_check"]["drawn"] = 0
    body["publication"]["checks"]["citation_check"]["no_text_layer"] += 1
    published.unlink()  # may be a hard link to a shared copy: replace, never write through
    published.write_text(canonical.dumps(body), encoding="utf-8")
    [problem] = _added_problems(data, published)
    assert "the recorded citation check" in problem
    assert "'drawn': 0" in problem
    assert "'drawn': 1" in problem


def _months() -> list[BillingPeriod]:
    return [
        BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1)),  # high season
        BillingPeriod(start=date(2026, 12, 1), end=date(2027, 1, 1)),  # low, a holiday
    ]


def _buckets() -> TimeOfUseBuckets:
    return TimeOfUseBuckets(
        used_kwh={
            TouPeriod.PEAK: Decimal("80.5"),
            TouPeriod.STANDARD: Decimal("210"),
            TouPeriod.OFF_PEAK: Decimal("301.25"),
        },
        # Off-peak exports more than it uses: the cap credits only the 301.25 kWh used.
        exported_kwh={TouPeriod.STANDARD: Decimal("120"), TouPeriod.OFF_PEAK: Decimal("400")},
    )


def _readings(period: BillingPeriod) -> IntervalReadings:
    days = (period.end - period.start).days
    start = datetime(period.start.year, period.start.month, 1, tzinfo=SAST)
    return IntervalReadings(
        minutes=60,
        readings=tuple(
            IntervalReading(
                start=start + timedelta(hours=n),
                used_kwh=Decimal("0.75"),
                exported_kwh=Decimal("0.5") if 10 <= (n % 24) < 14 else Decimal(0),
            )
            for n in range(days * 24)
        ),
    )


def test_the_version_survives_the_database_and_bills_identically(
    published: Path, data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """Equal as JSON text, not only as models; and the same bill from the file and from
    the database, for buckets with exports, interval readings and a quantity."""
    rebuild(data, test_database.migration)
    from_file = load_bytes(published.read_bytes(), TariffPublication).version
    assert from_file is not None
    file_vat = load_vat_table(DRAFTS / "vat/south-africa")
    database_vat = vat_table(connection, "south-africa", LATER)
    quantities = CustomerQuantities(annual_utilised_capacity_kva=Decimal("8"))
    for period in _months():
        recorded = tariff_version(connection, SUPPLIER, CODE, period.start, LATER).version
        assert recorded.model_dump_json() == from_file.model_dump_json()
        for usage in (_buckets(), _readings(period)):
            from_database = calculate_bill(
                recorded, period, usage, database_vat, quantities=quantities
            )
            from_files = calculate_bill(from_file, period, usage, file_vat, quantities=quantities)
            assert from_database.model_dump_json() == from_files.model_dump_json()
            credits = [line for line in from_files.lines if line.component == "export_credit"]
            assert credits
            assert all(line.amount.rand < 0 for line in credits)  # priced, not skipped
            if isinstance(usage, TimeOfUseBuckets):
                assert sum(line.quantity for line in credits) == Decimal("421.25")  # capped
            charged = {line.component for line in from_files.lines}
            assert ("network_capacity" in charged) is (period.start.month == 7)  # high only


def test_the_stored_checks_and_component_rows(
    published: Path, data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    rebuild(data, test_database.migration)
    stored = connection.execute(
        text("SELECT checks FROM publication WHERE id = :id"), {"id": PUBLICATION}
    ).scalar_one()
    assert stored == canonical.parse(_checks(published).model_dump_json(by_alias=True))
    assert stored["tool_version"] == "munisense publish 3"
    assert stored["citation_check"]["drawn"] == 1
    rows = connection.execute(
        text(
            "SELECT c.position, c.name, c.kind, c.status FROM tariff_component c"
            " JOIN tariff_version v ON v.id = c.tariff_version_id"
            " WHERE v.publication_id = :id ORDER BY c.position"
        ),
        {"id": PUBLICATION},
    ).all()
    assert [tuple(row) for row in rows] == [
        (0, "tou_energy", "time_of_use_energy", "estimated"),
        (1, "export_credit", "export_credit", "estimated"),
        (2, "network_capacity", "quantity_charge", "estimated"),
    ]
    status = connection.execute(
        text("SELECT status FROM tariff_version WHERE publication_id = :id"), {"id": PUBLICATION}
    ).scalar_one()
    assert status == "estimated"


def _expected(
    model: BaseModel, document: str | None = None, page: int = 0
) -> list[tuple[str, str]]:
    return sorted(
        (PUBLICATION, json.dumps(json.loads(cited.model_dump_json()), sort_keys=True))
        for _, cited in iter_cited(model)
        if document is None
        or (cited.citation.document_sha256, cited.citation.page) == (document, page)
    )


def _found(values: list[CitedValue]) -> list[tuple[str, str]]:
    return sorted(
        (v.publication_id, json.dumps(v.value, sort_keys=True))
        for v in values
        if v.publication_id == PUBLICATION
    )


def test_the_citation_and_status_queries_find_every_new_value(
    published: Path, data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """The repository's JSONPath walk reaches the calendar (season labels and dates, every
    range, the holiday list) and the new components, as the walker does."""
    rebuild(data, test_database.migration)
    version = _version()
    every = _expected(version)
    assert _found(values_with_status(connection, StatusKind.ESTIMATED, LATER)) == every
    calendar = [c for path, c in iter_cited(version) if path.startswith("tou_calendar.")]
    assert len(calendar) > 20
    pages = {(c.citation.document_sha256, c.citation.page) for _, c in iter_cited(version)}
    for document, page in pages:
        found = _found(values_citing(connection, document, page, LATER))
        assert found == _expected(version, document, page)
    assert _found(values_citing(connection, BOOK, 2, LATER)) == []  # a page it does not cite
