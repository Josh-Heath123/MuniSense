"""Storage for the time-of-use shapes (P4-12, ADR-0016 points 1, 3 and 6).

A made-up time-of-use version (a calendar with a holiday list, time-of-use energy, an
export credit with its cap, and a quantity charge limited to the high season) goes through the real
publish step, the publication guards and the loader, and is read back as the application
role. It must come back equal as JSON text and bill identically from the file and from the
database. Every value is a fixture marked "not real tariff data"; its citations are pointed
at a committed document only because the loader requires every cited document to be listed
(the citation checker is a stand-in).
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine

from munisense.domain.billing import (
    BillingPeriod,
    CustomerQuantities,
    IntervalReading,
    IntervalReadings,
    TimeOfUseBuckets,
    calculate_bill,
)
from munisense.domain.tariffs import DayType, ExportCap, TariffVersion, TouPeriod
from munisense.ingestion import guards
from munisense.ingestion.publish import Request, publish
from munisense.persistence.loader import rebuild
from munisense.persistence.repository import tariff_version, vat_table
from munisense.provenance.drafts import load_vat_table, write_file
from munisense.provenance.publication import TariffPublication, load_bytes, render
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
        data, Request(reason="t", draft=draft, check_only=True), clock, checker
    ).written
    publish(data, Request(reason="t", draft=draft), clock, checker)
    return data / "tariffs" / SUPPLIER / CODE / "2026-07-01.r1.json"


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


def test_the_guards_pass_the_set(published: Path, data: Path) -> None:
    assert guards.run_checks(data) == []


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
        exported_kwh={TouPeriod.STANDARD: Decimal("120"), TouPeriod.OFF_PEAK: Decimal("5")},
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
            billed = from_files.model_dump_json()
            assert '"export_credit"' in billed  # the credit is priced, not skipped
            assert ('"network_capacity"' in billed) is (period.start.month == 7)  # high only
