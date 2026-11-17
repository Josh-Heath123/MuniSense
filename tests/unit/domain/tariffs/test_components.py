"""Tariff components and tariff versions (P1-6, ADR-0004). Fixture values only."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from munisense.domain.citations import (
    Cited,
    ProvidedBy,
    StatusKind,
    TextCheck,
    UserProvided,
    Verified,
)
from munisense.domain.money import (
    Quantisation,
    Rate,
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
    PriceBasis,
    TariffVersion,
    VatTreatment,
)
from support.builders import (
    FIXTURE_STATUS,
    cited_date,
    cited_decimal,
    cited_rate,
    fixture_citation,
)

COMPONENT = TypeAdapter[Component](Component)
CENTS = Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_UP)
POLICY = RoundingPolicy(
    name="fixture",
    line_amount=CENTS,
    vat_application=VatApplication.PER_LINE,
    vat_amount=CENTS,
    total=CENTS,
    prepaid_kwh=None,
    status=FIXTURE_STATUS,
    evidence=(),
)


def standard_vat() -> Cited[VatTreatment]:
    return Cited[VatTreatment](
        value=VatTreatment.STANDARD, citation=fixture_citation(), status=FIXTURE_STATUS
    )


def block(up_to: str | None, cents: str) -> Block:
    return Block(
        up_to_kwh=None if up_to is None else cited_decimal(up_to),
        rate=cited_rate(cents, RateUnit.CENTS_PER_KWH),
    )


def blocks(*pairs: tuple[str | None, str]) -> BlockEnergy:
    return BlockEnergy(
        name="energy", vat=standard_vat(), blocks=tuple(block(u, r) for u, r in pairs)
    )


def fixed(value: str, unit: RateUnit) -> FixedCharge:
    return FixedCharge(name="basic", vat=standard_vat(), rate=cited_rate(value, unit))


def version(*components: Component, end: date | None = None) -> TariffVersion:
    return TariffVersion(
        supplier="fixture-metro",
        tariff_code="fixture-a",
        customer_class="residential",
        effective_from=cited_date(date(2026, 7, 1)),
        effective_to=None if end is None else cited_date(end),
        price_basis=Cited[PriceBasis](
            value=PriceBasis.EXCLUDING_VAT, citation=fixture_citation(), status=FIXTURE_STATUS
        ),
        rounding_policy=POLICY,
        components=components,
    )


THREE_BLOCKS = blocks(("50", "150.00"), ("350", "200.00"), (None, "250.00"))


# ------------------------------------------------------------------------- components


def test_a_block_component_has_ordered_blocks_with_an_open_last_block() -> None:
    assert [b.up_to_kwh.value if b.up_to_kwh else None for b in THREE_BLOCKS.blocks] == [
        Decimal("50"),
        Decimal("350"),
        None,
    ]


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
    ],
)
def test_invalid_blocks_are_refused(pairs: tuple[tuple[str | None, str], ...]) -> None:
    with pytest.raises(ValidationError):
        blocks(*pairs)


def test_an_empty_block_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        BlockEnergy(name="energy", vat=standard_vat(), blocks=())


def test_a_single_open_block_is_allowed() -> None:
    assert blocks((None, "180.00")).bounds() == [(Decimal(0), None)]


@pytest.mark.parametrize("unit", [RateUnit.RAND_PER_DAY, RateUnit.RAND_PER_MONTH])
def test_an_energy_rate_must_be_per_kwh(unit: RateUnit) -> None:
    with pytest.raises(ValidationError):
        FlatEnergy(name="energy", vat=standard_vat(), rate=cited_rate("1", unit))
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
        FlatEnergy(name="energy", vat=standard_vat(), rate=cited_rate("-1", RateUnit.CENTS_PER_KWH))


@pytest.mark.parametrize("name", ["", "Basic Charge", "x" * 65, "1abc"])
def test_a_component_name_is_a_short_slug(name: str) -> None:
    with pytest.raises(ValidationError):
        FixedCharge(name=name, vat=standard_vat(), rate=cited_rate("1", RateUnit.RAND_PER_MONTH))


def test_a_component_is_read_from_json_by_its_kind() -> None:
    component = COMPONENT.validate_json(THREE_BLOCKS.model_dump_json())
    assert isinstance(component, BlockEnergy)
    assert component == THREE_BLOCKS


def test_an_unknown_component_kind_or_schema_version_is_refused() -> None:
    data = THREE_BLOCKS.model_dump(mode="json")
    with pytest.raises(ValidationError):
        COMPONENT.validate_python(data | {"kind": "demand_charge"})
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(
            THREE_BLOCKS.model_dump_json().replace('"schema_version":1', '"schema_version":2')
        )


def test_component_rates_refuse_floats() -> None:
    payload = fixed("10", RateUnit.RAND_PER_MONTH).model_dump_json().replace('"10"', "10.0")
    with pytest.raises(ValidationError):
        COMPONENT.validate_json(payload)


# ----------------------------------------------------------------------------- status


def test_a_component_status_is_the_weakest_of_its_values() -> None:
    assert THREE_BLOCKS.status is StatusKind.ESTIMATED
    verified = Verified(
        verifier="owner",
        verifier_kind="human",
        method="fixture",
        verified_on=date(2026, 11, 17),
        text_check=TextCheck.PASSED,
    )
    user = UserProvided(provided_by=ProvidedBy.OWNER_BILL)
    charge = FixedCharge(
        name="basic",
        vat=Cited[VatTreatment](
            value=VatTreatment.STANDARD, citation=fixture_citation(), status=verified
        ),
        rate=Cited[Rate](
            value=Rate(value=Decimal("1"), unit=RateUnit.RAND_PER_MONTH),
            citation=fixture_citation(),
            status=user,
        ),
    )
    assert charge.status is StatusKind.USER_PROVIDED


# ---------------------------------------------------------------------------- version


def test_a_version_holds_an_ordered_list_of_components() -> None:
    tariff = version(fixed("200.00", RateUnit.RAND_PER_MONTH), THREE_BLOCKS)
    assert [c.name for c in tariff.components] == ["basic", "energy"]
    assert tariff.status is StatusKind.ESTIMATED


def test_a_version_json_round_trip_is_exact() -> None:
    tariff = version(fixed("200.0000", RateUnit.RAND_PER_MONTH), THREE_BLOCKS)
    again = TariffVersion.model_validate_json(tariff.model_dump_json())
    assert again == tariff
    assert '"200.0000"' in tariff.model_dump_json()


def test_duplicate_component_names_are_refused() -> None:
    with pytest.raises(ValidationError):
        version(fixed("1", RateUnit.RAND_PER_MONTH), fixed("2", RateUnit.RAND_PER_DAY))


def test_a_version_needs_at_least_one_component() -> None:
    with pytest.raises(ValidationError):
        version()


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


def test_a_flat_energy_component_and_its_status() -> None:
    flat = FlatEnergy(
        name="energy", vat=standard_vat(), rate=cited_rate("180.00", RateUnit.CENTS_PER_KWH)
    )
    assert flat.rate.value.canonical_value == Decimal("1.8000")
    assert flat.status is StatusKind.ESTIMATED


def test_a_version_with_an_end_date_includes_it_in_its_status() -> None:
    assert version(THREE_BLOCKS, end=date(2027, 7, 1)).status is StatusKind.ESTIMATED
