"""`uv run poe demo`: the README's example bill, priced by the engine from the real data.

City of Ekurhuleni Tariff B (Residential), single-phase, July 2026, 350 kWh, from the
cited drafts in `data/drafts/` (P1-9). The rendered Markdown is the README's example
table, and a test keeps the two identical, so the README cannot drift from the code.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from munisense.domain.billing import Bill, BillingPeriod, PeriodTotal, SourceRole, calculate_bill
from munisense.domain.money import Money
from munisense.domain.tariffs import TariffVersion
from munisense.provenance.drafts import load_file, load_vat_table

ROOT = Path(__file__).resolve().parents[3]
DRAFTS = ROOT / "data" / "drafts"
TARIFF = DRAFTS / "city-of-ekurhuleni" / "2026-27" / "b-residential-1-phase.json"
VAT = DRAFTS / "vat" / "south-africa"
JULY_2026 = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
KWH = Decimal(350)

# Short names for the committed source documents, by SHA-256 (data/sources/*/README.md).
DOCUMENTS = {
    "db55c0d359b41469d766c6196c51b59cbfe469a139b334f9c87195a92dc07e73": "Ekurhuleni schedule",
    "9204c3f8d0cea0200b84559f19bfa638d2f6eb6e2083ac633da4938eec52c31a": "SARS VAT 404",
}


def example_bill() -> Bill:
    """Tariff B, single-phase, July 2026, 350 kWh, priced from the drafts."""
    version = load_file(TARIFF, TariffVersion)
    vat_table = load_vat_table(VAT)
    return calculate_bill(version, JULY_2026, PeriodTotal(kwh=KWH), vat_table)


# The supply phase is part of the tariff code (one version per phase, P1-9).
PHASES = {"1-phase": "single-phase", "3-phase": "three-phase"}


def _phase(tariff_code: str) -> str:
    return next((name for code, name in PHASES.items() if tariff_code.endswith(code)), tariff_code)


def _rand(amount: Money) -> str:
    return f"R{amount.rand:,.2f}"


def _source(document: str, page: int) -> str:
    return f"{DOCUMENTS.get(document, document[:8])}, p. {page}"


def render(bill: Bill) -> str:
    """The bill as the README's Markdown: a table of lines, the totals and the warnings."""
    rows = [
        "| Line | Quantity | Rate | Amount | Source | Status |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for line in bill.lines:
        rate = next(s for s in line.sources if s.role is SourceRole.RATE)
        unit = line.rate.unit.value
        quantity = f"{line.quantity:f} {line.unit.value}"
        source = _source(rate.citation.document_sha256, rate.citation.page)
        rows.append(
            f"| {line.label} | {quantity} | R{line.rate.value:f}{unit.removeprefix('R')} "
            f"| {_rand(line.amount)} | {source} | {line.status.value} |"
        )
    percent = bill.vat_rate.percent
    rows += [
        f"| Subtotal | | | {_rand(bill.subtotal)} | | |",
        f"| VAT | {percent.value:f}% | | {_rand(bill.vat)} "
        f"| {_source(percent.citation.document_sha256, percent.citation.page)} "
        f"| {percent.kind.value} |",
        f"| **Total** | | | **{_rand(bill.total)}** | | **{bill.status.value}** |",
    ]
    warnings = [f"- {warning.message}" for warning in bill.warnings]
    heading = (
        f"{bill.tariff_name}, {_phase(bill.tariff_code)}, {bill.period.start:%B %Y}, "
        f"{bill.consumption_kwh:f} kWh (`uv run poe demo`):"
    )
    return "\n".join([heading, "", *rows, "", "Warnings on the bill:", "", *warnings])


def main() -> None:
    print(render(example_bill()))  # noqa: T201  # a command-line demo prints its result


if __name__ == "__main__":
    main()
