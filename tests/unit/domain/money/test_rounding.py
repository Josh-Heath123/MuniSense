"""Rounding policies with named quantisation points (P1-4, ADR-0005). Fixture policies only."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.citations import (
    Citation,
    Estimated,
    ProvidedBy,
    StatusKind,
    TextCheck,
    UserProvided,
    Verified,
)
from munisense.domain.money import (
    InvalidArithmeticError,
    Money,
    Quantisation,
    RoundingMode,
    RoundingPolicy,
    VatApplication,
)

CENT_HALF_UP = Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_UP)
ESTIMATED = Estimated(reason="fixture: not confirmed from real bills")


@pytest.mark.parametrize(
    ("mode", "value", "expected"),
    [
        (RoundingMode.HALF_UP, "2.345", "2.35"),
        (RoundingMode.HALF_UP, "-2.345", "-2.35"),
        (RoundingMode.HALF_UP, "2.344", "2.34"),
        (RoundingMode.HALF_EVEN, "2.346", "2.35"),
        (RoundingMode.UP, "-2.341", "-2.35"),
        (RoundingMode.HALF_UP, "-0.001", "0.00"),  # never negative zero
        (RoundingMode.HALF_EVEN, "2.345", "2.34"),
        (RoundingMode.HALF_EVEN, "2.355", "2.36"),
        (RoundingMode.DOWN, "2.349", "2.34"),
        (RoundingMode.DOWN, "-2.349", "-2.34"),
        (RoundingMode.UP, "2.341", "2.35"),
        (RoundingMode.FLOOR, "-2.341", "-2.35"),
        (RoundingMode.CEILING, "-2.349", "-2.34"),
    ],
)
def test_quantisation_modes(mode: RoundingMode, value: str, expected: str) -> None:
    quantisation = Quantisation(step=Decimal("0.01"), mode=mode)
    assert str(quantisation.apply(Decimal(value))) == expected


def test_quantisation_works_beyond_28_digits() -> None:
    value = Decimal("1" + "0" * 30 + ".005")
    assert CENT_HALF_UP.apply(value) == Decimal("1" + "0" * 30 + ".01")


def test_quantisation_to_whole_rands_and_to_tenths_of_a_kwh() -> None:
    assert Quantisation(step=Decimal("1"), mode=RoundingMode.HALF_UP).apply(
        Decimal("10.5")
    ) == Decimal("11")
    tenth = Quantisation(step=Decimal("0.1"), mode=RoundingMode.DOWN)
    assert str(tenth.apply(Decimal("42.79"))) == "42.7"


@pytest.mark.parametrize("step", ["0", "-0.01", "0.05", "2", "10", "0.25", "1E-13", "1E-60"])
def test_a_step_that_is_not_a_power_of_ten_at_most_one_is_refused(step: str) -> None:
    with pytest.raises(ValidationError):
        Quantisation(step=Decimal(step), mode=RoundingMode.HALF_UP)


def test_money_is_quantised_only_on_request() -> None:
    amount = Money(rand=Decimal("12.345"))
    assert amount.quantised(CENT_HALF_UP) == Money(rand=Decimal("12.35"))
    assert amount.rand == Decimal("12.345")


def test_a_policy_names_every_quantisation_point() -> None:
    policy = RoundingPolicy(
        name="fixture-cents-per-line",
        line_amount=CENT_HALF_UP,
        vat_application=VatApplication.PER_LINE,
        vat_amount=CENT_HALF_UP,
        total=CENT_HALF_UP,
        prepaid_kwh=Quantisation(step=Decimal("0.1"), mode=RoundingMode.DOWN),
        status=ESTIMATED,
        evidence=(),
    )
    assert policy.vat_application is VatApplication.PER_LINE
    assert policy.status.kind is StatusKind.ESTIMATED


def test_a_point_may_be_not_quantised() -> None:
    policy = RoundingPolicy(
        name="fixture-no-line-rounding",
        line_amount=None,
        vat_application=VatApplication.ON_SUBTOTAL,
        vat_amount=CENT_HALF_UP,
        total=CENT_HALF_UP,
        prepaid_kwh=None,
        status=ESTIMATED,
        evidence=(),
    )
    assert policy.line_amount is None


def test_a_policy_with_an_invalid_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        RoundingPolicy.model_validate(
            {
                "name": "x",
                "line_amount": None,
                "vat_application": "per_line",
                "vat_amount": None,
                "total": None,
                "prepaid_kwh": None,
                "status": {"kind": "estimated", "reason": ""},
                "evidence": (),
            }
        )


def test_a_policy_round_trips_through_json() -> None:
    policy = RoundingPolicy(
        name="fixture",
        line_amount=CENT_HALF_UP,
        vat_application=VatApplication.ON_SUBTOTAL,
        vat_amount=CENT_HALF_UP,
        total=None,
        prepaid_kwh=None,
        status=ESTIMATED,
        evidence=(),
    )
    assert RoundingPolicy.model_validate_json(policy.model_dump_json()) == policy


BILL = Citation(
    document_sha256="c" * 64, page=1, locator="fixture bill, VAT line", printed_text="15.00"
)
VERIFIED = Verified(
    verifier="owner",
    verifier_kind="human",
    method="fixture",
    verified_on=date(2026, 11, 17),
    text_check=TextCheck.NO_TEXT_LAYER,
)
USER = UserProvided(provided_by=ProvidedBy.OWNER_BILL)


def _policy(
    status: Verified | Estimated | UserProvided, evidence: tuple[Citation, ...]
) -> RoundingPolicy:
    return RoundingPolicy(
        name="fixture",
        line_amount=None,
        vat_application=VatApplication.ON_SUBTOTAL,
        vat_amount=None,
        total=None,
        prepaid_kwh=None,
        status=status,
        evidence=evidence,
    )


@pytest.mark.parametrize("status", [VERIFIED, USER])
def test_a_verified_or_user_provided_policy_must_cite_evidence(
    status: Verified | UserProvided,
) -> None:
    with pytest.raises(ValidationError):
        _policy(status, ())
    assert _policy(status, (BILL,)).evidence == (BILL,)


@pytest.mark.parametrize(("status", "warn"), [(VERIFIED, False), (ESTIMATED, True), (USER, True)])
def test_only_a_verified_policy_needs_no_warning(
    status: Verified | Estimated | UserProvided, warn: bool
) -> None:
    evidence = () if status is ESTIMATED else (BILL,)
    assert _policy(status, evidence).needs_warning is warn


def test_rounding_a_value_too_large_for_the_step_is_a_domain_error() -> None:
    with pytest.raises(InvalidArithmeticError):
        CENT_HALF_UP.apply(Decimal("1e58"))
    with pytest.raises(InvalidArithmeticError):
        Money(rand=Decimal("1e59")).quantised(CENT_HALF_UP)


# ------------------------------------------------------------------- quantised division


@pytest.mark.parametrize(
    ("mode", "numerator", "denominator", "expected"),
    [
        (RoundingMode.HALF_UP, "100", "1.15", "86.96"),  # 86.9565...
        (RoundingMode.DOWN, "100", "1.15", "86.95"),
        (RoundingMode.UP, "100", "1.15", "86.96"),
        (RoundingMode.HALF_UP, "1", "8", "0.13"),  # 0.125, an exact tie
        (RoundingMode.HALF_EVEN, "1", "8", "0.12"),
        (RoundingMode.FLOOR, "-1", "3", "-0.34"),
        (RoundingMode.CEILING, "-1", "3", "-0.33"),
        (RoundingMode.HALF_UP, "-1", "8", "-0.13"),
        (RoundingMode.HALF_UP, "-0.001", "1", "0.00"),
    ],
)
def test_divide_rounds_once_with_the_mode(
    mode: RoundingMode, numerator: str, denominator: str, expected: str
) -> None:
    quantisation = Quantisation(step=Decimal("0.01"), mode=mode)
    assert str(quantisation.divide(Decimal(numerator), Decimal(denominator))) == expected


def test_divide_decides_correctly_far_beyond_60_digits() -> None:
    # 1/3 + 1e-80 sits just above 0.333...; rounding UP to 0.01 must give 0.34 even though
    # the difference is 80 digits down.
    numerator = Decimal(1) + Decimal("3e-80")
    up = Quantisation(step=Decimal("0.01"), mode=RoundingMode.UP)
    assert up.divide(numerator, Decimal(3)) == Decimal("0.34")
    exact_tie = Quantisation(step=Decimal("0.01"), mode=RoundingMode.UP)
    assert exact_tie.divide(Decimal("0.99"), Decimal(3)) == Decimal("0.33")


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [("1", "0"), ("NaN", "1"), ("1", "Infinity")],
)
def test_divide_refuses_zero_and_non_finite(numerator: str, denominator: str) -> None:
    with pytest.raises(InvalidArithmeticError):
        CENT_HALF_UP.divide(Decimal(numerator), Decimal(denominator))
