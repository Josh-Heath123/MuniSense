"""`uv run poe demo`: the README's example bill, priced by the engine from published data.

City of Ekurhuleni Tariff B (Residential), single-phase, July 2026, 350 kWh, read from the
database as currently recorded (P2-12's repository, as the application role), so the dev
database must be running and rebuilt from the committed publications first
(`docker compose up -d db`, `uv run poe db-rebuild`). The rendered Markdown is the README's
example table, and a test keeps the two identical, so the README cannot drift from the code
or the published data (P2-13, closes TD-13).
"""

import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

from munisense.domain.billing import Bill, BillingPeriod, PeriodTotal, SourceRole, calculate_bill
from munisense.domain.money import Money
from munisense.persistence.connection import (
    DatabaseNotReadyError,
    DatabaseUnavailableError,
    connect,
)
from munisense.persistence.repository import NotRecordedError, tariff_version, vat_table
from munisense.platform.settings import DatabaseUrl, SettingsError, database_url

SUPPLIER = "city-of-ekurhuleni"
TARIFF = "b-residential-1-phase"
COUNTRY = "south-africa"
JULY_2026 = BillingPeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
KWH = Decimal(350)

# Short names for the committed source documents, by SHA-256 (data/sources/*/README.md).
DOCUMENTS = {
    "db55c0d359b41469d766c6196c51b59cbfe469a139b334f9c87195a92dc07e73": "Ekurhuleni schedule",
    "9204c3f8d0cea0200b84559f19bfa638d2f6eb6e2083ac633da4938eec52c31a": "SARS VAT 404",
}


def example_bill(url: DatabaseUrl, recorded_on: datetime) -> Bill:
    """Tariff B, single-phase, July 2026, 350 kWh, as recorded on `recorded_on`."""
    with connect(url) as connection:
        recorded = tariff_version(connection, SUPPLIER, TARIFF, JULY_2026.start, recorded_on)
        vat = vat_table(connection, COUNTRY, recorded_on)
    return calculate_bill(recorded.version, JULY_2026, PeriodTotal(kwh=KWH), vat)


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


def _now() -> datetime:
    return datetime.now(UTC)


def main(env: Mapping[str, str] = os.environ, now: Callable[[], datetime] = _now) -> int:
    """Print the example bill as currently recorded.

    Returns 2 for unsafe settings, and 1 with the reason and what to do when the database
    cannot be reached, has no tables or holds nothing recorded.
    """
    try:
        bill = example_bill(database_url(env, "MUNISENSE_DATABASE_URL"), now())
    except SettingsError as error:
        sys.stderr.write(f"demo: {error}\n")
        return 2
    except DatabaseUnavailableError as error:
        sys.stderr.write(
            f"demo: {error}; is it running (`docker compose up -d db`), and do the"
            " MUNISENSE_DATABASE_URL settings match it?\n"
        )
        return 1
    except DatabaseNotReadyError as error:
        sys.stderr.write(
            f"demo: {error}; run `uv run poe db-bootstrap` once, then `uv run poe db-rebuild`\n"
        )
        return 1
    except NotRecordedError as error:
        sys.stderr.write(f"demo: {error}; load the publications with `uv run poe db-rebuild`\n")
        return 1
    sys.stdout.write(render(bill) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover  # the command line runs main()
    raise SystemExit(main())
