"""The repository: "as recorded on" queries (P2-12; ADR-0003, ADR-0012 sections 2 and 4).

The data is published by the real publish step into a copy of the committed data, loaded by
the real loader, and read back as the application role.
"""

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Connection, Engine, text

from munisense.domain.billing import (
    BillingPeriod,
    PeriodTotal,
    calculate_bill,
    calculate_month,
    calculate_period,
)
from munisense.domain.citations import ProvidedBy, StatusKind, UserProvided
from munisense.domain.money import Money, VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion.citation_check import iter_cited
from munisense.persistence.loader import rebuild
from munisense.persistence.repository import (
    CitedValue,
    NotRecordedError,
    tariff_version,
    values_citing,
    values_with_status,
    vat_table,
)
from munisense.provenance.drafts import load_file, load_vat_table, write_file
from support.database import TestDatabase
from support.ekurhuleni import BILL_CASES, month
from support.publishing import (
    DRAFTS,
    R1,
    TARIFF,
    draft_b1,
    publish_all,
    publish_one,
    replace_draft,
)

SUPPLIER, B1 = TARIFF.split("/")
B3 = "b-residential-3-phase"
TARIFF_DRAFTS = DRAFTS / "city-of-ekurhuleni/2026-27"
VAT_DRAFT = DRAFTS / "vat/south-africa/2018-04-01.json"
LATER = datetime(2027, 1, 1, tzinfo=UTC)  # after every test publication
TICK = timedelta(microseconds=1)
SCHEDULE = "db55c0d359b41469d766c6196c51b59cbfe469a139b334f9c87195a92dc07e73"  # Ekurhuleni


@pytest.fixture
def connection(app_engine: Engine) -> Iterator[Connection]:
    with app_engine.connect() as c:
        yield c


def _published_at(connection: Connection) -> dict[str, datetime]:
    rows = connection.execute(text("SELECT id, published_at FROM publication"))
    return {row.id: row.published_at for row in rows}


def _months() -> list[BillingPeriod]:
    return [month(2026 + (6 + n) // 12, (6 + n) % 12 + 1) for n in range(12)]


def _loaded(data: Path, test_database: TestDatabase) -> None:
    publish_all(data)
    rebuild(data, test_database.migration)


def test_versions_and_vat_survive_the_round_trip(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """Equal as JSON text, not only as models: a Decimal's scale (3.3700) must survive too."""
    _loaded(data, test_database)
    file_vat = load_vat_table(DRAFTS / "vat/south-africa")
    database_vat = vat_table(connection, "south-africa", LATER)
    assert database_vat.model_dump_json() == file_vat.model_dump_json()
    for code in (B1, B3):
        version = load_file(TARIFF_DRAFTS / f"{code}.json", TariffVersion)
        for period in _months():
            recorded = tariff_version(connection, SUPPLIER, code, period.start, LATER)
            assert recorded.version.model_dump_json() == version.model_dump_json()
            for kwh in ("0", "350", "123.45", "50.5", "812.4", "101.4"):
                usage = PeriodTotal(kwh=Decimal(kwh))
                from_database = calculate_bill(recorded.version, period, usage, database_vat)
                from_files = calculate_bill(version, period, usage, file_vat)
                assert from_database.model_dump_json() == from_files.model_dump_json()


def _rand(value: str) -> Money:
    return Money(rand=Decimal(value))


@pytest.mark.parametrize(
    ("phase", "period", "kwh", "lines", "subtotal", "vat", "total"), BILL_CASES
)
def test_the_hand_checked_bills_from_the_database(  # one row of the P1 table
    data: Path,
    test_database: TestDatabase,
    connection: Connection,
    phase: str,
    period: BillingPeriod,
    kwh: str,
    lines: list[str],
    subtotal: str,
    vat: str,
    total: str,
) -> None:
    _loaded(data, test_database)
    version = tariff_version(
        connection, SUPPLIER, f"b-residential-{phase}", period.start, LATER
    ).version
    vat_rates = vat_table(connection, "south-africa", LATER)
    bill = calculate_bill(version, period, PeriodTotal(kwh=Decimal(kwh)), vat_rates)
    assert [line.amount for line in bill.lines] == [_rand(amount) for amount in lines]
    assert (bill.subtotal, bill.vat, bill.total) == (_rand(subtotal), _rand(vat), _rand(total))


def test_the_split_period_and_prepaid_examples_from_the_database(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """The P1-9 split-period and P1-15 prepaid examples, priced from database rows."""
    _loaded(data, test_database)
    b1 = tariff_version(connection, SUPPLIER, B1, date(2026, 7, 15), LATER).version
    vat_rates = vat_table(connection, "south-africa", LATER)
    period = BillingPeriod(start=date(2026, 7, 15), end=date(2026, 8, 15))
    split = calculate_period([b1], period, PeriodTotal(kwh=Decimal(300)), vat_rates)
    assert [part.total for part in split.parts] == [_rand("706.81"), _rand("582.08")]
    assert split.total == _rand("1288.89")
    purchases = calculate_month(
        b1,
        [(date(2026, 7, 1), _rand("500.00")), (date(2026, 7, 15), _rand("300.00"))],
        vat_rates,
    )
    assert [p.fixed_charges for p in purchases] == [_rand("126.25"), Money.zero()]
    assert [p.kwh for p in purchases] == [Decimal("96.44"), Decimal("77.41")]


def test_a_correction_and_a_withdrawal_change_answers_only_from_their_published_at(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    clock = publish_all(data)
    replace_draft(data, load_file(TARIFF_DRAFTS / f"{B1}.json", TariffVersion))
    publish_one(data, clock, draft=draft_b1(data), supersedes=R1)
    publish_one(data, clock, withdraw=f"{TARIFF}/2026-07-01/r2")
    replace_draft(
        data, load_file(TARIFF_DRAFTS / f"{B1}.json", TariffVersion)
    )  # publishing used it
    publish_one(data, clock, draft=draft_b1(data))  # restored, superseding nothing
    rebuild(data, test_database.migration)
    at = _published_at(connection)
    r1, r2, r3, r4 = (at[f"{TARIFF}/2026-07-01/r{n}"] for n in (1, 2, 3, 4))
    on = date(2026, 7, 15)

    def answer(moment: datetime) -> str | None:
        try:
            return tariff_version(connection, SUPPLIER, B1, on, moment).publication_id
        except NotRecordedError:
            return None

    expected = [
        (r1 - TICK, None),  # not yet published
        (r1, R1),
        (r2 - TICK, R1),
        (r2, f"{TARIFF}/2026-07-01/r2"),
        (r3 - TICK, f"{TARIFF}/2026-07-01/r2"),
        (r3, None),  # withdrawn
        (r4 - TICK, None),
        (r4, f"{TARIFF}/2026-07-01/r4"),
    ]
    assert [answer(moment) for moment, _ in expected] == [want for _, want in expected]
    # The same instants written in another zone, asked in a session in a third zone.
    connection.execute(text("SELECT set_config('TimeZone', 'Pacific/Kiritimati', false)"))
    johannesburg = ZoneInfo("Africa/Johannesburg")
    assert [answer(moment.astimezone(johannesburg)) for moment, _ in expected] == [
        want for _, want in expected
    ]
    assert tariff_version(connection, SUPPLIER, B1, on, r4).published_at == r4

    def b1_publications(moment: datetime) -> set[str]:
        found = values_with_status(connection, StatusKind.ESTIMATED, moment)
        return {v.publication_id for v in found if v.publication_id.startswith(TARIFF)}

    def b1_citing(moment: datetime) -> set[str]:
        found = values_citing(connection, SCHEDULE, 4, moment)  # the basic charge's page
        return {v.publication_id for v in found if v.publication_id.startswith(TARIFF)}

    for query in (b1_publications, b1_citing):
        assert query(r2 - TICK) == {R1}
        assert query(r2) == {f"{TARIFF}/2026-07-01/r2"}  # r1 left at r2
        assert query(r3) == set()  # withdrawn
        assert query(r4) == {f"{TARIFF}/2026-07-01/r4"}


def test_a_date_outside_every_version_is_not_recorded(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    publish_all(data)
    rebuild(data, test_database.migration)
    for on in (date(2026, 6, 30), date(2027, 7, 1)):
        with pytest.raises(NotRecordedError, match="no version of city-of-ekurhuleni/b-resid"):
            tariff_version(connection, SUPPLIER, B1, on, LATER)
    with pytest.raises(NotRecordedError, match="no version"):
        tariff_version(connection, SUPPLIER, "no-such-tariff", date(2026, 7, 1), LATER)


def test_a_record_moment_needs_a_time_zone(connection: Connection) -> None:
    naive = datetime(2027, 1, 1)  # noqa: DTZ001  # the point of the test
    with pytest.raises(ValueError, match="needs a time zone"):
        tariff_version(connection, SUPPLIER, B1, date(2026, 7, 1), naive)
    with pytest.raises(ValueError, match="needs a time zone"):
        vat_table(connection, "south-africa", naive)
    with pytest.raises(TypeError, match="must be a date, not a datetime"):
        tariff_version(connection, SUPPLIER, B1, LATER, LATER)


def test_no_vat_rate_recorded_is_refused(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    publish_all(data)
    rebuild(data, test_database.migration)
    vat = _published_at(connection)["vat/south-africa/2018-04-01/r1"]
    with pytest.raises(NotRecordedError, match="no VAT rate of south-africa was recorded"):
        vat_table(connection, "south-africa", vat - TICK)
    assert len(vat_table(connection, "south-africa", vat).rates) == 1


def test_vat_rates_with_a_gap_are_refused(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """Test data only (a temporary copy, never committed): the 2018 rate is given an end,
    and a second rate starts a month after it, re-using the 2018 rate's cited values. The
    page does not print these dates: only the stand-in checker ever sees them."""
    clock = publish_all(data)
    rate = load_file(VAT_DRAFT, VatRate)
    end = rate.start_cited.model_copy(update={"value": date(2030, 1, 1)})
    later = rate.start_cited.model_copy(update={"value": date(2030, 2, 1)})
    draft = data / "drafts/vat/south-africa/2018-04-01.json"
    draft.unlink(missing_ok=True)  # publishing used it
    write_file(draft, rate.model_copy(update={"end_cited": end}))
    publish_one(data, clock, draft=draft, supersedes="vat/south-africa/2018-04-01/r1")
    second = data / "drafts/vat/south-africa/2030-02-01.json"
    write_file(second, rate.model_copy(update={"start_cited": later}))
    publish_one(data, clock, draft=second)
    rebuild(data, test_database.migration)
    with pytest.raises(NotRecordedError, match="do not form a contiguous table"):
        vat_table(connection, "south-africa", LATER)


def _expected(models: Sequence[tuple[str, object]]) -> list[tuple[str, str]]:
    """Every cited value in the models (a model may itself be one cited value)."""
    return sorted(
        (publication, json.dumps(json.loads(cited.model_dump_json()), sort_keys=True))
        for publication, model in models
        for _, cited in iter_cited(model)
    )


def _found(values: list[CitedValue]) -> list[tuple[str, str]]:
    return sorted((v.publication_id, json.dumps(v.value, sort_keys=True)) for v in values)


def test_citation_and_status_queries_find_every_cited_value(
    data: Path, test_database: TestDatabase, connection: Connection
) -> None:
    """Test data only (a temporary copy): one 3-phase value is marked user-provided, so the
    status query is shown to select by kind, not to return everything."""
    clock = publish_all(data)
    b3 = load_file(TARIFF_DRAFTS / f"{B3}.json", TariffVersion)
    basic = b3.components[0]
    weak = basic.label.model_copy(
        update={"status": UserProvided(provided_by=ProvidedBy.OWNER_BILL)}
    )
    corrected = b3.model_copy(
        update={"components": (basic.model_copy(update={"label": weak}), *b3.components[1:])}
    )
    draft = data / f"drafts/city-of-ekurhuleni/2026-27/{B3}.json"
    draft.unlink(missing_ok=True)
    write_file(draft, corrected)
    publish_one(data, clock, draft=draft, supersedes=f"{SUPPLIER}/{B3}/2026-07-01/r1")
    rebuild(data, test_database.migration)
    models: list[tuple[str, object]] = [
        (R1, load_file(TARIFF_DRAFTS / f"{B1}.json", TariffVersion)),
        (f"{SUPPLIER}/{B3}/2026-07-01/r2", corrected),
        ("vat/south-africa/2018-04-01/r1", load_file(VAT_DRAFT, VatRate)),
    ]
    every = _expected(models)
    user = _expected([(f"{SUPPLIER}/{B3}/2026-07-01/r2", weak)])
    assert len(user) == 1
    assert _found(values_with_status(connection, StatusKind.USER_PROVIDED, LATER)) == user
    estimated = _found(values_with_status(connection, StatusKind.ESTIMATED, LATER))
    assert estimated == [value for value in every if value not in user]
    assert values_with_status(connection, StatusKind.VERIFIED, LATER) == []
    pages = {
        (cited.citation.document_sha256, cited.citation.page)
        for _, model in models
        for _, cited in iter_cited(model)
    }
    assert len(pages) > 1
    for document, page in pages:
        want = _expected(
            [
                (publication, cited)
                for publication, model in models
                for _, cited in iter_cited(model)
                if (cited.citation.document_sha256, cited.citation.page) == (document, page)
            ]
        )
        assert _found(values_citing(connection, document, page, LATER)) == want
    assert values_citing(connection, "0" * 64, 1, LATER) == []
    before = _published_at(connection)["vat/south-africa/2018-04-01/r1"] - TICK
    assert values_with_status(connection, StatusKind.ESTIMATED, before) == []
