"""Publication envelopes: identity rules, withdrawals and the load path (P2-4, ADR-0012)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from munisense.domain.money import VatTable
from munisense.domain.tariffs import TariffVersion
from munisense.provenance import canonical
from munisense.provenance.canonical import CanonicalJsonError
from munisense.provenance.publication import (
    CONVERTERS,
    ParsedId,
    PublicationError,
    TariffPublication,
    VatRatePublication,
    load,
    render,
)

ROOT = Path(__file__).resolve().parents[3]
TARIFF = TariffVersion.model_validate_json(
    (ROOT / "data/drafts/ekurhuleni/2026-27/tariff-b-residential-1-phase.json").read_text()
)
VAT = VatTable.model_validate_json((ROOT / "data/drafts/vat/south-africa.json").read_text())
TARIFF_ID = "city-of-ekurhuleni/b-residential-1-phase/2026-07-01"
VAT_ID = "vat/south-africa/2018-04-01"


def _record(publication_id: str, supersedes: str | None = None) -> dict[str, Any]:
    return {
        "id": publication_id,
        "published_at": "2026-12-01T09:30:00+02:00",
        "published_by": "owner",
        "supersedes": supersedes,
        "reason": "test publication",
        "checks": {
            "tool_version": "munisense 0.0.0",
            "schema_valid": True,
            "documents_listed_and_hashes_match": True,
            "overlaps": "none",
            "citation_check": {"passed": 0, "no_text_layer": 31, "failed": 0},
        },
    }


def _tariff(publication_id: str, supersedes: str | None = None, *, version: bool = True) -> str:
    body = {
        "schema_version": 1,
        "publication": _record(publication_id, supersedes),
        "version": json.loads(TARIFF.model_dump_json()) if version else None,
    }
    return canonical.dumps(body)


def _vat(publication_id: str, supersedes: str | None = None, *, version: bool = True) -> str:
    body = {
        "schema_version": 1,
        "publication": _record(publication_id, supersedes),
        "version": json.loads(VAT.rates[-1].model_dump_json()) if version else None,
    }
    return canonical.dumps(body)


def test_a_tariff_publication_round_trips_through_its_canonical_text() -> None:
    text = _tariff(f"{TARIFF_ID}/r1")
    publication = load(text, TariffPublication)
    assert publication.version == TARIFF
    assert render(publication) == text
    assert publication.publication.published_at == datetime(2026, 12, 1, 7, 30, tzinfo=UTC)
    assert not publication.is_withdrawal


def test_a_vat_rate_publication_round_trips_through_its_canonical_text() -> None:
    text = _vat(f"{VAT_ID}/r1")
    publication = load(text, VatRatePublication)
    assert publication.version == VAT.rates[-1]
    assert render(publication) == text


def test_render_keeps_the_models_key_order() -> None:
    text = render(load(_tariff(f"{TARIFF_ID}/r1"), TariffPublication))
    assert list(json.loads(text)) == ["schema_version", "publication", "version"]


def test_a_correction_supersedes_the_revision_before_it() -> None:
    publication = load(_tariff(f"{TARIFF_ID}/r2", f"{TARIFF_ID}/r1"), TariffPublication)
    assert publication.publication.supersedes == f"{TARIFF_ID}/r1"


def test_a_correction_may_move_to_another_effective_date() -> None:
    old = "city-of-ekurhuleni/b-residential-1-phase/2026-06-01/r1"
    assert load(_tariff(f"{TARIFF_ID}/r2", old), TariffPublication).version == TARIFF


@pytest.mark.parametrize(
    ("publication_id", "supersedes", "message"),
    [
        (f"{TARIFF_ID}/r2", None, "must supersede the revision before it"),
        (f"{TARIFF_ID}/r1", "city-of-ekurhuleni/b-residential-1-phase/2026-06-01/r1", "after"),
        (f"{TARIFF_ID}/r3", f"{TARIFF_ID}/r1", "must be the revision after"),
        (
            f"{TARIFF_ID}/r2",
            "city-of-ekurhuleni/b-residential-3-phase/2026-07-01/r1",
            "same tariff",
        ),
        ("city-of-ekurhuleni/b-residential-3-phase/2026-07-01/r1", None, "does not match"),
        ("city-of-ekurhuleni/b-residential-1-phase/2026-08-01/r1", None, "does not match"),
        ("vat/b-residential-1-phase/2026-07-01/r1", None, "cannot use the VAT scope"),
    ],
)
def test_tariff_identity_rules(publication_id: str, supersedes: str | None, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        load(_tariff(publication_id, supersedes), TariffPublication)


@pytest.mark.parametrize(
    ("publication_id", "message"),
    [
        ("vat/south-africa/2019-04-01/r1", "start date"),
        ("vat/elsewhere/2018-04-01/r1", "starts with vat/south-africa/"),
    ],
)
def test_vat_identity_rules(publication_id: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        load(_vat(publication_id), VatRatePublication)


def test_a_withdrawal_holds_no_version_and_supersedes_the_same_date() -> None:
    withdrawal = load(
        _tariff(f"{TARIFF_ID}/r2", f"{TARIFF_ID}/r1", version=False), TariffPublication
    )
    assert withdrawal.is_withdrawal
    vat = load(_vat(f"{VAT_ID}/r2", f"{VAT_ID}/r1", version=False), VatRatePublication)
    assert vat.is_withdrawal


@pytest.mark.parametrize(
    ("make", "kind"), [(_tariff, TariffPublication), (_vat, VatRatePublication)]
)
def test_a_withdrawal_must_supersede_something(make: Any, kind: Any) -> None:
    scope = TARIFF_ID if kind is TariffPublication else VAT_ID
    with pytest.raises(ValidationError, match="must name the publication it withdraws"):
        load(make(f"{scope}/r1", version=False), kind)


def test_a_withdrawal_is_filed_under_the_withdrawn_date() -> None:
    old = "city-of-ekurhuleni/b-residential-1-phase/2026-06-01/r1"
    with pytest.raises(ValidationError, match="filed under the withdrawn version's date"):
        load(_tariff(f"{TARIFF_ID}/r2", old, version=False), TariffPublication)


def test_a_naive_record_time_is_refused() -> None:
    text = _tariff(f"{TARIFF_ID}/r1").replace("2026-12-01T09:30:00+02:00", "2026-12-01T09:30:00")
    with pytest.raises(ValidationError, match="timezone"):
        load(text, TariffPublication)


def test_a_failed_citation_check_cannot_be_published() -> None:
    text = _tariff(f"{TARIFF_ID}/r1").replace('"failed": 0', '"failed": 1')
    with pytest.raises(ValidationError, match="failed"):
        load(text, TariffPublication)


def test_a_name_is_refused_as_publisher() -> None:
    text = _tariff(f"{TARIFF_ID}/r1").replace('"published_by": "owner"', '"published_by": "A Name"')
    with pytest.raises(ValidationError, match="published_by"):
        load(text, TariffPublication)


def test_load_refuses_text_that_is_not_canonical() -> None:
    with pytest.raises(CanonicalJsonError, match="canonical form"):
        load(_tariff(f"{TARIFF_ID}/r1").removesuffix("\n"), TariffPublication)


@pytest.mark.parametrize("version", [2, 0, "1", True, None])
def test_load_refuses_an_unknown_schema_version(version: object) -> None:
    body = json.loads(_tariff(f"{TARIFF_ID}/r1"))
    body["schema_version"] = version
    with pytest.raises(PublicationError, match="unknown schema_version"):
        load(canonical.dumps(body), TariffPublication)


def test_load_refuses_a_file_that_is_not_an_object() -> None:
    with pytest.raises(PublicationError, match="one JSON object"):
        load("[]\n", TariffPublication)


def test_only_schema_version_1_exists_and_converts_to_itself() -> None:
    assert sorted(CONVERTERS) == [1]
    assert CONVERTERS[1]({"a": 1}) == {"a": 1}


def test_a_malformed_id_is_refused() -> None:
    with pytest.raises(PublicationError, match="not a publication id"):
        ParsedId.of("city-of-ekurhuleni/2026-07-01/r1")
