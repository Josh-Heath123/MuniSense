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
    StatusKind,
    TextCheck,
    UserProvided,
    Verified,
    weakest,
)
from munisense.domain.money import ExactDecimal, Rate, RateUnit

SHA = "a" * 64


def citation(**overrides: object) -> Citation:
    fields: dict[str, object] = {
        "document_sha256": SHA,
        "page": 7,
        "locator": "Table 1, row 'Block 1'",
        "printed_text": "234.67",
    }
    fields.update(overrides)
    return Citation.model_validate(fields)


VERIFIED = Verified(
    verifier="owner",
    method="compared with the printed page",
    verified_on=date(2026, 11, 17),
    text_check=TextCheck.PASSED,
)
ESTIMATED = Estimated(reason="citation check not built until P2")
USER = UserProvided(provided_by="owner, from a prepaid receipt")


# -------------------------------------------------------------------------- citation


def test_a_citation_keeps_document_page_locator_and_printed_text() -> None:
    cited = citation()
    assert (cited.page, cited.printed_text) == (7, "234.67")


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_sha256": "A" * 64},  # upper case is not the canonical form
        {"document_sha256": "a" * 63},
        {"page": 0},
        {"page": 1.0},
        {"page": "7"},
        {"locator": ""},
        {"printed_text": ""},
        {"printed_text": "x" * 501},
        {"locator": "x" * 201},
    ],
)
def test_an_invalid_citation_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        citation(**overrides)


# --------------------------------------------------------------------------- statuses


def test_estimated_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        Estimated(reason="")
    with pytest.raises(ValidationError):
        Estimated(reason="   ")


def test_user_provided_needs_who_provided_it() -> None:
    with pytest.raises(ValidationError):
        UserProvided(provided_by="")


@pytest.mark.parametrize("field", ["verifier", "method"])
def test_verified_needs_a_verifier_and_a_method(field: str) -> None:
    fields = VERIFIED.model_dump()
    fields[field] = ""
    with pytest.raises(ValidationError):
        Verified.model_validate(fields)


def test_a_status_is_read_from_json_by_its_kind() -> None:
    cited = Cited[ExactDecimal].model_validate_json(
        '{"value": "1.5", "citation": null, "status": {"kind": "estimated", "reason": "fixture"}}'
    )
    assert isinstance(cited.status, Estimated)
    assert cited.status.kind is StatusKind.ESTIMATED


def test_an_unknown_status_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate_json(
            '{"value": "1.5", "citation": null, "status": {"kind": "guessed", "reason": "x"}}'
        )


# ------------------------------------------------------------------------ cited values


def test_a_cited_value_holds_any_domain_value() -> None:
    rate = Rate(value=Decimal("234.67"), unit=RateUnit.CENTS_PER_KWH)
    cited = Cited[Rate](value=rate, citation=citation(), status=ESTIMATED)
    assert cited.value.canonical_value == Decimal("2.3467")
    assert cited.kind is StatusKind.ESTIMATED


def test_a_verified_value_needs_a_citation() -> None:
    with pytest.raises(ValidationError):
        Cited[ExactDecimal](value=Decimal("1"), citation=None, status=VERIFIED)


def test_an_estimated_or_user_provided_value_may_lack_a_citation() -> None:
    # For example a rounding rule inferred from bills, or a figure from a user's receipt.
    assert Cited[ExactDecimal](value=Decimal("1"), citation=None, status=ESTIMATED).citation is None
    assert Cited[ExactDecimal](value=Decimal("1"), citation=None, status=USER).citation is None


def test_a_cited_value_still_refuses_floats() -> None:
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate({"value": 1.5, "citation": None, "status": ESTIMATED})
    with pytest.raises(ValidationError):
        Cited[ExactDecimal].model_validate_json(
            '{"value": 1.5, "citation": null, "status": {"kind": "estimated", "reason": "x"}}'
        )


def test_a_cited_value_round_trips_through_json_exactly() -> None:
    rate = Rate(value=Decimal("234.6700"), unit=RateUnit.CENTS_PER_KWH)
    cited = Cited[Rate](value=rate, citation=citation(), status=VERIFIED)
    assert Cited[Rate].model_validate_json(cited.model_dump_json()) == cited


def test_a_scanned_page_is_recorded_as_such_when_verified() -> None:
    status = Verified(
        verifier="owner",
        method="read the scanned page",
        verified_on=date(2026, 11, 17),
        text_check=TextCheck.NO_TEXT_LAYER,
    )
    assert status.text_check is TextCheck.NO_TEXT_LAYER


# ---------------------------------------------------------------------------- weakest


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([VERIFIED], StatusKind.VERIFIED),
        ([VERIFIED, USER], StatusKind.USER_PROVIDED),
        ([USER, VERIFIED, ESTIMATED], StatusKind.ESTIMATED),
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


def test_status_order_is_estimated_then_user_provided_then_verified() -> None:
    assert StatusKind.ESTIMATED.rank < StatusKind.USER_PROVIDED.rank < StatusKind.VERIFIED.rank
