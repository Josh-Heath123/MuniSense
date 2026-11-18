"""Tariff components and tariff versions (P1-6, ADR-0004). Fixture values only."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from munisense.domain.citations import ProvidedBy, StatusKind, TextCheck, UserProvided, Verified
from munisense.domain.money import (
    Quantisation,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    VatApplication,
)
from munisense.domain.periods import DateRange
from munisense.domain.tariffs import (
    Block,
    BlockEnergy,
    Component,
    FixedCharge,
    FlatEnergy,
    TariffVersion,
)
from support.builders import (
    FIXTURE_STATUS,
    Status,
    cited_basis,
    cited_date,
    cited_decimal,
    cited_label,
    cited_rate,
    cited_vat,
    fixture_billing_policy,
)

COMPONENT = TypeAdapter[Component](Component)
CENTS = Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_UP)
POLICY = RoundingPolicy(
    name="fixture",
    line_amount=CENTS,
    vat_application=VatApplication.PER_LINE,
    vat_amount=CENTS,
    total=CENTS,
    pro_rating=None,
    prepaid_kwh=None,
    status=FIXTURE_STATUS,
    evidence=(),
)
VERIFIED = Verified(
    verifier="owner",
    verifier_kind="human",
    method="fixture",
    verified_on=date(2026, 11, 17),
    text_check=TextCheck.PASSED,
)
USER = UserProvided(provided_by=ProvidedBy.OWNER_BILL)


def block(up_to: str | None, cents: str, status: Status = FIXTURE_STATUS) -> Block:
    return Block(
        up_to_kwh=None if up_to is None else cited_decimal(up_to, status),
        rate=cited_rate(cents, RateUnit.CENTS_PER_KWH, status),
    )


def blocks(*pairs: tuple[str | None, str]) -> BlockEnergy:
    return BlockEnergy(
        schema_version=1,
        kind="block_energy",
        name="energy",
        label=cited_label("Energy charge"),
        vat=cited_vat(),
        blocks=tuple(block(u, r) for u, r in pairs),
    )


def fixed(value: str, unit: RateUnit, name: str = "basic") -> FixedCharge:
    return FixedCharge(
        schema_version=1,
        kind="fixed_charge",
        name=name,
        label=cited_label("Basic charge"),
        vat=cited_vat(),
        rate=cited_rate(value, unit),
    )


def flat(value: str, unit: RateUnit = RateUnit.CENTS_PER_KWH) -> FlatEnergy:
    return FlatEnergy(
        schema_version=1,
        kind="flat_energy",
        name="energy",
        label=cited_label("Energy charge"),
        vat=cited_vat(),
        rate=cited_rate(value, unit),
    )


def version(*components: Component, end: date | None = None) -> TariffVersion:
    return TariffVersion(
        schema_version=1,
        supplier="fixture-metro",
        tariff_code="fixture-a",
        customer_class="residential",
        printed_name=cited_label("Tariff A: Domestic"),
        applies_to=cited_label("Domestic, prepaid"),
        effective_from=cited_date(date(2026, 7, 1)),
        effective_to=None if end is None else cited_date(end),
        price_basis=cited_basis(),
        rounding_policy=POLICY,
        billing_policy=fixture_billing_policy(),
        components=components,
    )


THREE_BLOCKS = blocks(("50", "150.00"), ("350", "200.00"), (None, "250.00"))


def _without_schema_version(payload: str) -> str:
    assert '"schema_version":1,' in payload
    return payload.replace('"schema_version":1,', "", 1)


# ------------------------------------------------------------------------- components


def test_block_bounds_give_each_block_its_width() -> None:
    assert THREE_BLOCKS.bounds() == [
        (Decimal(0), Decimal(50)),
        (Decimal(50), Decimal(350)),
        (Decimal(350), None),
    ]


@pytest.mark.parametrize(
    "pairs",
    [
        (("350", "1"), ("50", "2"), (None, "3")),  # unordered
        (("50", "1"), ("50", "2"), (None, "3")),  # equal thresholds
        (("50", "1"), ("350", "2")),  # last block not open-ended
        (("50", "1"), (None, "2"), (None, "3")),  # open-ended block before the last
        (("0", "1"), (None, "2")),  # a block of zero width
        (("-5", "1"), (None, "2")),  # a negative threshold
        (("50", "-1"), (None, "2")),  # a negative rate
        (("50", "-0"), (None, "2")),  # a negative zero rate
    ],
)
def test_invalid_blocks_are_refused(pairs: tuple[tuple[str | None, str], ...]) -> None:
    with pytest.raises(ValidationError):
        blocks(*pairs)


def test_an_empty_or_oversized_block_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        blocks()
    many = (*((str(i), "1") for i in range(1, 21)), (None, "1"))
    with pytest.raises(ValidationError):
        blocks(*many)


def test_twenty_blocks_and_a_single_open_block_are_allowed() -> None:
    twenty = (*((str(i), "1") for i in range(1, 20)), (None, "1"))
    assert len(blocks(*twenty).blocks) == 20
    assert blocks((None, "180.00")).bounds() == [(Decimal(0), None)]


def test_a_zero_rate_is_allowed() -> None:
    assert flat("0").rate.value.value == 0
    assert blocks(("50", "0"), (None, "1")).blocks[0].rate.value.value == 0


@pytest.mark.parametrize("unit", [RateUnit.RAND_PER_DAY, RateUnit.RAND_PER_MONTH])
def test_an_energy_rate_must_be_per_kwh(unit: RateUnit) -> None:
    with pytest.raises(ValidationError):
        flat("1", unit)
    with pytest.raises(ValidationError):
        Block(up_to_kwh=None, rate=cited_rate("1", unit))


@pytest.mark.parametrize("unit", [RateUnit.CENTS_PER_KWH, RateUnit.RAND_PER_KWH])
def test_a_fixed_charge_must_be_per_day_or_per_month(unit: RateUnit) -> None:
    with pytest.raises(ValidationError):
        fixed("1", unit)


def test_negative_rates_are_refused() -> None:
    with pytest.raises(ValidationError):
        fixed("-1", RateUnit.RAND_PER_MONTH)
    with pytest.raises(ValidationError):
        flat("-1")


@pytest.mark.parametrize("name", ["", "Basic Charge", "x" * 65, "1abc"])
def test_a_component_name_is_a_short_slug(name: str) -> None:
    with pytest.raises(ValidationError):
        fixed("1", RateUnit.RAND_PER_MONTH, name=name)


@pytest.mark.parametrize("label", ["", "   ", "Basic\ncharge", "x" * 201])
def test_a_printed_label_is_bounded_plain_text(label: str) -> None:
    with pytest.raises(ValidationError):
        cited_label(label)


def test_a_component_is_read_from_json_by_its_kind() -> None:
    component = COMPONENT.validate_json(THREE_BLOCKS.model_dump_json())
    assert isinstance(component, BlockEnergy)
    assert component == THREE_BLOCKS


def test_an_unknown_kind_or_a_missing_or_unknown_schema_version_is_refused() -> None:
    payload = THREE_BLOCKS.model_dump_json()
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(payload.replace('"kind":"block_energy"', '"kind":"demand"'))
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(payload.replace('"schema_version":1', '"schema_version":2'))
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(_without_schema_version(payload))


def test_component_rates_refuse_floats() -> None:
    payload = fixed("10", RateUnit.RAND_PER_MONTH).model_dump_json().replace('"10"', "10.0")
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(payload)


# ----------------------------------------------------------------------------- status


def verified_version(weak: str | None) -> TariffVersion:
    """A version whose every value is verified, except the one named by `weak`."""

    def status(position: str) -> Status:
        return USER if position == weak else VERIFIED

    energy = BlockEnergy(
        schema_version=1,
        kind="block_energy",
        name="energy",
        label=cited_label("Energy", status("block_label")),
        vat=cited_vat(status=status("block_vat")),
        blocks=(
            Block(
                up_to_kwh=cited_decimal("50", status("block_threshold")),
                rate=cited_rate("150", RateUnit.CENTS_PER_KWH, status("block_rate_1")),
            ),
            Block(
                up_to_kwh=None,
                rate=cited_rate("250", RateUnit.CENTS_PER_KWH, status("block_rate_2")),
            ),
        ),
    )
    basic = FixedCharge(
        schema_version=1,
        kind="fixed_charge",
        name="basic",
        label=cited_label("Basic", status("fixed_label")),
        vat=cited_vat(status=status("fixed_vat")),
        rate=cited_rate("200", RateUnit.RAND_PER_MONTH, status("fixed_rate")),
    )
    network = FlatEnergy(
        schema_version=1,
        kind="flat_energy",
        name="network",
        label=cited_label("Network", status("flat_label")),
        vat=cited_vat(status=status("flat_vat")),
        rate=cited_rate("10", RateUnit.CENTS_PER_KWH, status("flat_rate")),
    )
    return TariffVersion(
        schema_version=1,
        supplier="fixture-metro",
        tariff_code="fixture-a",
        customer_class="residential",
        printed_name=cited_label("Tariff A", status("printed_name")),
        applies_to=cited_label("Domestic", status("applies_to")),
        effective_from=cited_date(date(2026, 7, 1), status("effective_from")),
        effective_to=cited_date(date(2027, 7, 1), status("effective_to")),
        price_basis=cited_basis(status=status("price_basis")),
        rounding_policy=POLICY,
        billing_policy=fixture_billing_policy(),
        components=(basic, energy, network),
    )


# position -> the component it belongs to (None for the version header)
POSITIONS: dict[str, str | None] = {
    "printed_name": None,
    "applies_to": None,
    "effective_from": None,
    "effective_to": None,
    "price_basis": None,
    "fixed_label": "basic",
    "fixed_vat": "basic",
    "fixed_rate": "basic",
    "block_label": "energy",
    "block_vat": "energy",
    "block_threshold": "energy",
    "block_rate_1": "energy",
    "block_rate_2": "energy",
    "flat_label": "network",
    "flat_vat": "network",
    "flat_rate": "network",
}


def test_a_fully_verified_version_and_its_components_are_verified() -> None:
    tariff = verified_version(None)
    assert tariff.status is StatusKind.VERIFIED
    assert all(c.status is StatusKind.VERIFIED for c in tariff.components)


@pytest.mark.parametrize(("weak", "component"), POSITIONS.items())
def test_one_weaker_value_anywhere_weakens_the_summary(weak: str, component: str | None) -> None:
    tariff = verified_version(weak)
    assert tariff.status is StatusKind.USER_PROVIDED
    weakened = [c.name for c in tariff.components if c.status is StatusKind.USER_PROVIDED]
    assert weakened == ([] if component is None else [component])


@pytest.mark.parametrize("weak", [None, "effective_to", "block_rate_2"])
def test_a_version_with_mixed_statuses_round_trips_exactly(weak: str | None) -> None:
    tariff = verified_version(weak)
    assert TariffVersion.model_validate_json(tariff.model_dump_json()) == tariff


# ---------------------------------------------------------------------------- version


def test_a_version_holds_an_ordered_list_of_components() -> None:
    tariff = version(fixed("200.00", RateUnit.RAND_PER_MONTH), THREE_BLOCKS)
    assert [c.name for c in tariff.components] == ["basic", "energy"]


def test_a_version_json_round_trip_keeps_printed_precision() -> None:
    tariff = version(fixed("200.0000", RateUnit.RAND_PER_MONTH), THREE_BLOCKS)
    assert TariffVersion.model_validate_json(tariff.model_dump_json()) == tariff
    assert '"200.0000"' in tariff.model_dump_json()


def test_a_version_with_a_missing_or_unknown_schema_version_is_refused() -> None:
    payload = version(THREE_BLOCKS).model_dump_json()
    assert payload.startswith('{"schema_version":1,')
    with pytest.raises(ValidationError):
        TariffVersion.model_validate_json(_without_schema_version(payload))
    with pytest.raises(ValidationError):
        TariffVersion.model_validate_json(
            payload.replace('"schema_version":1', '"schema_version":2', 1)
        )


def test_duplicate_component_names_are_refused() -> None:
    with pytest.raises(ValidationError):
        version(fixed("1", RateUnit.RAND_PER_MONTH), fixed("2", RateUnit.RAND_PER_DAY))


def test_a_version_needs_one_to_thirty_components() -> None:
    with pytest.raises(ValidationError):
        version()
    many = [fixed("1", RateUnit.RAND_PER_MONTH, name=f"c{i}") for i in range(31)]
    with pytest.raises(ValidationError):
        version(*many)


def test_a_version_must_end_after_it_starts() -> None:
    with pytest.raises(ValidationError):
        version(THREE_BLOCKS, end=date(2026, 7, 1))


@pytest.mark.parametrize(
    ("start", "end", "covered"),
    [
        (date(2026, 7, 1), date(2026, 8, 1), True),
        (date(2027, 6, 1), date(2027, 7, 1), True),  # the last month before the end
        (date(2027, 6, 15), date(2027, 7, 15), False),  # runs past the end
        (date(2026, 6, 15), date(2026, 7, 15), False),  # starts before the version
    ],
)
def test_a_version_covers_periods_inside_its_effective_range(
    start: date, end: date, covered: bool
) -> None:
    tariff = version(THREE_BLOCKS, end=date(2027, 7, 1))
    assert tariff.covers(DateRange(start=start, end=end)) is covered


def test_an_open_ended_version_covers_any_later_period() -> None:
    tariff = version(THREE_BLOCKS)
    assert tariff.covers(DateRange(start=date(2030, 1, 1), end=date(2030, 2, 1)))
