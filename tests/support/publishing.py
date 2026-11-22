"""Publications made by the real publish step in a copy of the data (P2-11, P2-12).

The citation checker is a stand-in: the tests are about storage, not citations.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from munisense.domain.citations import iter_cited
from munisense.domain.money import VatRate
from munisense.domain.tariffs import TariffVersion
from munisense.ingestion.citation_check import CitationResult, Outcome
from munisense.ingestion.publish import Request, publish
from munisense.provenance.drafts import write_file
from munisense.provenance.sources import SourceDocument

ROOT = Path(__file__).resolve().parents[2]
# The three drafts as they were before their first publication (P2-13, E55).
DRAFTS = ROOT / "tests" / "fixtures" / "drafts"
TARIFF = "city-of-ekurhuleni/b-residential-1-phase"
R1 = f"{TARIFF}/2026-07-01/r1"
START = datetime(2026, 12, 1, 9, 30, tzinfo=UTC)


class Clock:
    """Each call is one minute after the last."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def checker(
    model: BaseModel, _sources: dict[str, tuple[Path, SourceDocument]]
) -> list[CitationResult]:
    ok = Outcome.PASSED if isinstance(model, VatRate) else Outcome.NO_TEXT_LAYER
    return [CitationResult(p, c.citation.page, ok, "stand-in") for p, c in iter_cited(model)]


def draft_b1(data: Path) -> Path:
    return data / "drafts/city-of-ekurhuleni/2026-27/b-residential-1-phase.json"


def replace_draft(data: Path, version: TariffVersion) -> None:
    """Replace the B1 draft (unlink first: the data folder may hold hard links)."""
    draft_b1(data).unlink(missing_ok=True)
    write_file(draft_b1(data), version)


def publish_one(data: Path, clock: Clock, **request: object) -> None:
    publish(data, Request(reason="t", **request), clock, checker)  # type: ignore[arg-type]


def publish_all(data: Path) -> Clock:
    """The VAT rate, then tariff B 1-phase and 3-phase, one minute apart."""
    clock = Clock()
    publish_one(data, clock, draft=data / "drafts/vat/south-africa/2018-04-01.json")
    publish_one(data, clock, draft=draft_b1(data))
    publish_one(
        data, clock, draft=data / "drafts/city-of-ekurhuleni/2026-27/b-residential-3-phase.json"
    )
    return clock
