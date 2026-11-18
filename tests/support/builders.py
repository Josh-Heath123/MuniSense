"""Builders for fixture tariffs. Fixture values are invented and cite a fixture document.

Nothing here is real tariff data (CLAUDE.md rule 1). Real Ekurhuleni figures, from P1-9,
are built with real citations to the committed source document instead. Production code
may never import this package (import-linter rule 6).
"""

from datetime import date
from decimal import Decimal

from munisense.domain.citations import Citation, Cited, Estimated, UserProvided, Verified
from munisense.domain.money import (
    ExactDecimal,
    Quantisation,
    Rate,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    VatApplication,
    VatRate,
    VatTable,
)
from munisense.domain.tariffs import (
    BillingPolicy,
    Block,
    BlockEnergy,
    Component,
    ConsumptionSplit,
    FixedCharge,
    FlatEnergy,
    FreeBasicAllocation,
    Levy,
    PriceBasis,
    ProRating,
    Season,
    SeasonalEnergy,
    SeasonDates,
    TariffVersion,
    VatTreatment,
)
from munisense.domain.tariffs.components import PrintedLabel

FIXTURE_DOCUMENT = "f" * 64
FIXTURE_STATUS = Estimated(reason="test fixture; not real tariff data")
type Status = Verified | Estimated | UserProvided


def fixture_citation(text: str = "fixture") -> Citation:
    return Citation(
        document_sha256=FIXTURE_DOCUMENT, page=1, locator="fixture table", printed_text=text
    )


def cited_decimal(value: str, status: Status = FIXTURE_STATUS) -> Cited[ExactDecimal]:
    return Cited[ExactDecimal](
        value=Decimal(value), citation=fixture_citation(value), status=status
    )


def cited_rate(value: str, unit: RateUnit, status: Status = FIXTURE_STATUS) -> Cited[Rate]:
    return Cited[Rate](
        value=Rate(value=Decimal(value), unit=unit),
        citation=fixture_citation(value),
        status=status,
    )


def cited_date(value: date, status: Status = FIXTURE_STATUS) -> Cited[date]:
    return Cited[date](value=value, citation=fixture_citation(value.isoformat()), status=status)


def cited_label(value: str, status: Status = FIXTURE_STATUS) -> Cited[PrintedLabel]:
    return Cited[PrintedLabel](value=value, citation=fixture_citation(value), status=status)


def cited_vat(
    value: VatTreatment = VatTreatment.STANDARD, status: Status = FIXTURE_STATUS
) -> Cited[VatTreatment]:
    return Cited[VatTreatment](value=value, citation=fixture_citation(), status=status)


def cited_basis(
    value: PriceBasis = PriceBasis.EXCLUDING_VAT, status: Status = FIXTURE_STATUS
) -> Cited[PriceBasis]:
    return Cited[PriceBasis](value=value, citation=fixture_citation(), status=status)


# --------------------------------------------------------------- fixture tariff versions


CENTS_HALF_UP = Quantisation(step=Decimal("0.01"), mode=RoundingMode.HALF_UP)
MILLIONTHS_HALF_UP = Quantisation(step=Decimal("0.000001"), mode=RoundingMode.HALF_UP)


def fixture_billing_policy(status: Status = FIXTURE_STATUS) -> BillingPolicy:
    return BillingPolicy(
        name="fixture-billing",
        pro_rating=ProRating.BY_DAYS,
        consumption_split=ConsumptionSplit.BY_DAYS,
        status=status,
        evidence=() if isinstance(status, Estimated) else (fixture_citation("pro rata"),),
    )


def fixture_policy(
    *,
    line_amount: Quantisation | None = CENTS_HALF_UP,
    vat_application: VatApplication = VatApplication.ON_SUBTOTAL,
    vat_amount: Quantisation | None = CENTS_HALF_UP,
    total: Quantisation | None = CENTS_HALF_UP,
    pro_rating: Quantisation | None = MILLIONTHS_HALF_UP,
    status: Status = FIXTURE_STATUS,
    name: str = "fixture",
) -> RoundingPolicy:
    estimated = isinstance(status, Estimated)
    return RoundingPolicy(
        name=name,
        line_amount=line_amount,
        vat_application=vat_application,
        vat_amount=vat_amount,
        total=total,
        pro_rating=pro_rating,
        prepaid_kwh=None,
        status=status,
        evidence=() if estimated else (fixture_citation("fixture bill"),),
    )


def fixture_blocks(
    *pairs: tuple[str | None, str],
    name: str = "energy",
    vat: VatTreatment = VatTreatment.STANDARD,
    status: Status = FIXTURE_STATUS,
) -> BlockEnergy:
    """Block energy from (up to kWh or None, cents per kWh) pairs."""
    return BlockEnergy(
        schema_version=1,
        kind="block_energy",
        name=name,
        label=cited_label("Energy charge", status),
        vat=cited_vat(vat, status),
        blocks=tuple(
            Block(
                up_to_kwh=None if up_to is None else cited_decimal(up_to, status),
                rate=cited_rate(cents, RateUnit.CENTS_PER_KWH, status),
            )
            for up_to, cents in pairs
        ),
    )


def fixture_fixed(
    value: str,
    unit: RateUnit = RateUnit.RAND_PER_MONTH,
    name: str = "basic",
    status: Status = FIXTURE_STATUS,
) -> FixedCharge:
    return FixedCharge(
        schema_version=1,
        kind="fixed_charge",
        name=name,
        label=cited_label("Basic charge", status),
        vat=cited_vat(status=status),
        rate=cited_rate(value, unit, status),
    )


def fixture_flat(cents: str, name: str = "energy") -> FlatEnergy:
    return FlatEnergy(
        schema_version=1,
        kind="flat_energy",
        name=name,
        label=cited_label("Energy charge"),
        vat=cited_vat(),
        rate=cited_rate(cents, RateUnit.CENTS_PER_KWH),
    )


def fixture_levy(
    value: str,
    unit: RateUnit = RateUnit.CENTS_PER_KWH,
    name: str = "levy",
    vat: VatTreatment = VatTreatment.STANDARD,
    status: Status = FIXTURE_STATUS,
) -> Levy:
    return Levy(
        schema_version=1,
        kind="levy",
        name=name,
        label=cited_label("Fixture levy", status),
        vat=cited_vat(vat, status),
        rate=cited_rate(value, unit, status),
    )


def fixture_free_basic(
    free_kwh: str,
    energy_component: str = "energy",
    name: str = "free_basic",
    vat: VatTreatment = VatTreatment.STANDARD,
    status: Status = FIXTURE_STATUS,
) -> FreeBasicAllocation:
    return FreeBasicAllocation(
        schema_version=1,
        kind="free_basic_allocation",
        name=name,
        label=cited_label("Free basic electricity", status),
        vat=Cited[VatTreatment](
            value=vat, citation=fixture_citation("free basic VAT"), status=status
        ),
        free_kwh=cited_decimal(free_kwh, status),
        energy_component=energy_component,
    )


def fixture_season(
    name: str,
    start: tuple[int, int],
    end: tuple[int, int],
    *pairs: tuple[str | None, str],
    status: Status = FIXTURE_STATUS,
) -> Season:
    """A season from `start` to `end` (month, day; inclusive) with blocks as in
    `fixture_blocks`; one `(None, cents)` pair is a flat rate."""
    dates = SeasonDates(start_month=start[0], start_day=start[1], end_month=end[0], end_day=end[1])
    return Season(
        name=name,
        label=cited_label(f"{name} season", status),
        dates=Cited[SeasonDates](
            value=dates, citation=fixture_citation(f"{name} dates"), status=status
        ),
        blocks=tuple(
            Block(
                up_to_kwh=None if up_to is None else cited_decimal(up_to, status),
                rate=cited_rate(cents, RateUnit.CENTS_PER_KWH, status),
            )
            for up_to, cents in pairs
        ),
    )


def fixture_seasonal(*seasons: Season, name: str = "energy") -> SeasonalEnergy:
    return SeasonalEnergy(
        schema_version=1,
        kind="seasonal_energy",
        name=name,
        label=cited_label("Energy charge"),
        vat=cited_vat(),
        seasons=seasons,
    )


def fixture_version(
    *components: Component,
    start: date = date(2026, 7, 1),
    end: date | None = date(2027, 7, 1),
    policy: RoundingPolicy | None = None,
    basis: PriceBasis = PriceBasis.EXCLUDING_VAT,
    status: Status = FIXTURE_STATUS,
    billing: BillingPolicy | None = None,
    tariff_code: str = "fixture-a",
) -> TariffVersion:
    return TariffVersion(
        schema_version=1,
        supplier="fixture-metro",
        tariff_code=tariff_code,
        customer_class="residential",
        printed_name=cited_label("Fixture tariff", status),
        applies_to=cited_label("Fixture customers", status),
        effective_from=cited_date(start, status),
        effective_to=None if end is None else cited_date(end, status),
        price_basis=cited_basis(basis, status),
        rounding_policy=policy or fixture_policy(status=status),
        billing_policy=billing or fixture_billing_policy(status=status),
        components=components,
    )


def fixture_vat_table(percent: str = "12.5", status: Status = FIXTURE_STATUS) -> VatTable:
    """A fixture VAT table. 12.5% is deliberately not South Africa's real rate."""
    return VatTable(
        rates=(
            VatRate(
                start_cited=cited_date(date(2000, 1, 1), status),
                end_cited=None,
                percent=cited_decimal(percent, status),
            ),
        )
    )
