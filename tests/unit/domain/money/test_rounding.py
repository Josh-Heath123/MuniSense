"""Rounding policies with named quantisation points (P1-4, ADR-0005). Fixture policies only."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from munisense.domain.citations import Estimated, StatusKind
from munisense.domain.money import (
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


@pytest.mark.parametrize("step", ["0", "-0.01", "0.05", "2", "10", "0.25"])
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
    )
    assert policy.vat_application is VatApplication.PER_LINE
    assert policy.status.kind is StatusKind.ESTIMATED
    assert policy.is_estimated


def test_a_point_may_be_not_quantised() -> None:
    policy = RoundingPolicy(
        name="fixture-no-line-rounding",
        line_amount=None,
        vat_application=VatApplication.ON_SUBTOTAL,
        vat_amount=CENT_HALF_UP,
        total=CENT_HALF_UP,
        prepaid_kwh=None,
        status=ESTIMATED,
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
    )
    assert RoundingPolicy.model_validate_json(policy.model_dump_json()) == policy
