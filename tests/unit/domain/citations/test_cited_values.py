"""Cited values and verification statuses (P1-3, ADR-0006). Values here are fixtures."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.citations import (
    Citation,
    Cited,
    Estimated,
    NoStatusesError,
    ProvidedBy,
    StatusKind,
    TextCheck,
    UnparameterisedCitedError,
    UserProvided,
    Verified,
    cited_statuses,
    weakest,
)
from munisense.domain.money import ExactDecimal, Rate, RateUnit

SHA = "a" * 64
CITATION_FIELDS: dict[str, object] = {
    "document_sha256": SHA,
    "page": 7,
    "locator": "Table 1, row 'Block 1'",
    "printed_text": "234.67",
}


def citation(**overrides: object) -> Citation:
    return Citation.model_validate(CITATION_FIELDS | overrides)


VERIFIED = Verified(
    verifier="owner",
    verifier_kind="human",
    method="compared with the printed page",
    verified_on=date(2026, 11, 17),
    text_check=TextCheck.PASSED,
)
ESTIMATED = Estimated(reason="citation check not built until P2")
USER = UserProvided(provided_by=ProvidedBy.OWNER_PREPAID_RECEIPT)
STATUS_JSON = '{"kind": "estimated", "reason": "fixture"}'


def _citation_json() -> str:
    return citation().model_dump_json()


# -------------------------------------------------------------------------- citation


def test_a_citation_keeps_document_page_locator_and_printed_text() -> None:
    cited = citation()
    assert (cited.page, cited.printed_text) == (7, "234.67")


def test_printed_text_is_kept_exactly_including_newlines() -> None:
    assert citation(printed_text=" 234.67\n c/kWh").printed_text == " 234.67\n c/kWh"


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_sha256": "A" * 64},  # upper case is not the canonical form
        {"document_sha256": "a" * 63},
        {"page": 0},
        {"page": 1.0},
        {"page": "7"},
        {"page": True},
        {"locator": ""},
        {"locator": "   "},
        {"locator": "x" * 201},
        {"locator": "row\x1b[31m"},
        {"locator": "row\nforged log line"},
        {"printed_text": ""},
        {"printed_text": " "},
        {"printed_text": "\n"},
        {"printed_text": "x" * 501},
        {"printed_text": "1\x00"},
    ],
)
def test_an_invalid_citation_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        citation(**overrides)


# --------------------------------------------------------------------------- statuses


def test_a_valid_status_round_trips_in_python_mode() -> None:
    # Positive control for the refusals below: the round trip itself is valid.
    assert Verified.model_validate(VERIFIED.model_dump()) == VERIFIED
    assert Estimated.model_validate({"kind": "estimated", "reason": "x"}).reason == "x"


def test_estimated_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        Estimated(reason="")
    with pytest.raises(ValidationError):
        Estimated(reason="   ")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verifier", ""),
        ("verifier", "Jane Doe"),  # a handle, never a name
        ("verifier", "jane@example.org"),
        ("verifier_kind", "agent"),  # ADR-0006: an agent's check alone is not enough
        ("method", ""),
    ],
)
def test_verified_needs_a_human_verifier_handle_and_a_method(field: str, value: str) -> None:
    fields = VERIFIED.model_dump() | {field: value}
    with pytest.raises(ValidationError):
        Verified.model_validate(fields)


@pytest.mark.parametrize("provided_by", ["", "Jane Doe, account 1234567", "owner"])
def test_user_provided_takes_a_source_category_not_free_text(provided_by: str) -> None:
    with pytest.raises(ValidationError):
        UserProvided.model_validate({"provided_by": provided_by})


def test_fields_of_another_status_kind_are_refused() -> None:
    with pytest.raises(ValidationError):
        Estimated.model_validate({"kind": "estimated", "reason": "x", "verifier": "owner"})


def test_a_status_is_read_from_json_by_its_kind() -> None:
    cited = Cited[ExactDecimal].model_validate_json(
        f'{{"value": "1.5", "citation": {_citation_json()}, "status": {STATUS_JSON}}}'
    )
    assert isinstance(cited.status, Estimated)
    assert cited.kind is StatusKind.ESTIMATED


def test_an_unknown_status_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate_json(
            f'{{"value": "1.5", "citation": {_citation_json()},'
            ' "status": {"kind": "guessed", "reason": "x"}}'
        )


# ------------------------------------------------------------------------ cited values


def test_a_cited_value_holds_any_domain_value() -> None:
    rate = Rate(value=Decimal("234.67"), unit=RateUnit.CENTS_PER_KWH)
    cited = Cited[Rate](value=rate, citation=citation(), status=ESTIMATED)
    assert cited.value.canonical_value == Decimal("2.3467")
    assert cited.kind is StatusKind.ESTIMATED


@pytest.mark.parametrize("status", [VERIFIED, ESTIMATED, USER])
def test_every_cited_value_needs_a_citation_whatever_its_status(
    status: Verified | Estimated | UserProvided,
) -> None:
    # ADR-0006: each value has its own citation.
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate(
            {"value": Decimal("1"), "citation": None, "status": status}
        )


def test_a_cited_value_still_refuses_floats() -> None:
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate(
            {"value": 1.5, "citation": citation(), "status": ESTIMATED}
        )
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate_json(
            f'{{"value": 1.5, "citation": {_citation_json()}, "status": {STATUS_JSON}}}'
        )


def test_an_unparameterised_cited_refuses_to_validate() -> None:
    with pytest.raises(UnparameterisedCitedError):
        Cited.model_validate_json(
            f'{{"value": 1.5, "citation": {_citation_json()}, "status": {STATUS_JSON}}}'
        )


def test_a_cited_value_round_trips_through_json_exactly() -> None:
    rate = Rate(value=Decimal("234.6700"), unit=RateUnit.CENTS_PER_KWH)
    cited = Cited[Rate](value=rate, citation=citation(), status=VERIFIED)
    assert Cited[Rate].model_validate_json(cited.model_dump_json()) == cited


def test_a_scanned_page_is_recorded_as_such_when_verified() -> None:
    status = Verified.model_validate(
        VERIFIED.model_dump() | {"text_check": TextCheck.NO_TEXT_LAYER}
    )
    assert status.text_check is TextCheck.NO_TEXT_LAYER


# ---------------------------------------------------------------------------- weakest


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([VERIFIED], StatusKind.VERIFIED),
        ([VERIFIED, ESTIMATED], StatusKind.ESTIMATED),
        ([ESTIMATED, VERIFIED, USER], StatusKind.USER_PROVIDED),
        ([ESTIMATED, ESTIMATED], StatusKind.ESTIMATED),
    ],
)
def test_weakest_status_summarises_a_set(
    statuses: list[Verified | Estimated | UserProvided], expected: StatusKind
) -> None:
    assert weakest(statuses) is expected


def test_weakest_of_nothing_is_refused() -> None:
    with pytest.raises(NoStatusesError):
        weakest([])


def test_status_order_is_user_provided_then_estimated_then_verified() -> None:
    assert StatusKind.USER_PROVIDED.rank < StatusKind.ESTIMATED.rank < StatusKind.VERIFIED.rank


def test_cited_statuses_walks_models_tuples_lists_and_dicts() -> None:
    one = Cited[ExactDecimal](value=Decimal("1"), citation=citation(), status=VERIFIED)
    two = Cited[ExactDecimal](value=Decimal("2"), citation=citation(), status=USER)
    found = cited_statuses({"a": [one, (two,)], "b": "not cited", "c": 3})
    assert [s.kind for s in found] == [StatusKind.VERIFIED, StatusKind.USER_PROVIDED]
    assert cited_statuses(citation()) == []
