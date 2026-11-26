"""The Eskom drawn lists (P4-11, ADR-0016 point 5): every listed text gives `drawn` on its
committed page, and the book and the schedule list the same clock readings."""

from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import BaseModel

from munisense.domain.citations import Citation, Cited, Estimated
from munisense.ingestion.citation_check import Outcome, check_citations
from munisense.ingestion.publish import documents
from munisense.provenance.drafts import load_file
from munisense.provenance.sources import SourceManifest

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
BOOK, SCHEDULE = (
    "tariffs-and-charges-booklet-2026-27.pdf",
    "schedule-of-standard-prices-2026-27.pdf",
)


class _Values(BaseModel):
    values: tuple[Cited[str], ...]


def _manifest() -> SourceManifest:
    return load_file(DATA / "sources/eskom/sources.json", SourceManifest)


def _listed() -> dict[tuple[str, int], tuple[str, ...]]:
    return {
        (document.file, item.page): item.texts
        for document in _manifest().documents
        for item in document.drawn or ()
    }


def test_three_pages_are_listed() -> None:
    assert {key: len(texts) for key, texts in _listed().items()} == {
        (SCHEDULE, 33): 1,
        (SCHEDULE, 56): 29,
        (BOOK, 45): 29,
    }


def test_the_book_and_the_schedule_list_the_same_ranges() -> None:
    """A consistency check of the transcriptions, not proof that the pages agree."""
    listed = _listed()
    book = [text.replace("-Demand", " Demand") for text in listed[(BOOK, 45)]]
    assert book == list(listed[(SCHEDULE, 56)])


def test_each_ring_covers_the_day_once() -> None:
    rings: dict[str, list[tuple[int, int]]] = {}
    for text in _listed()[(BOOK, 45)]:
        ring, _, reading = text.partition(": ")
        *_, start, _to, end = reading.split(" ")
        rings.setdefault(ring, []).append((int(start) % 24, int(end)))
    assert len(rings) == 6
    for ranges in rings.values():
        hours = sorted(ranges)
        assert hours[0][0] == 0
        assert hours[-1][1] == 24
        assert all(a[1] == b[0] for a, b in pairwise(hours))


@pytest.mark.slow
def test_every_listed_text_gives_drawn_on_its_page() -> None:
    sources = documents(DATA)
    values = [
        Cited[str](
            value="x",
            citation=Citation(
                document_sha256=document.sha256,
                page=item.page,
                locator="drawn item",
                printed_text=text,
                drawn=True,
            ),
            status=Estimated(reason="test"),
        )
        for document in _manifest().documents
        for item in document.drawn or ()
        for text in item.texts
    ]
    results = check_citations(_Values(values=tuple(values)), sources)
    assert len(results) == 59
    assert {r.outcome for r in results} == {Outcome.DRAWN}, [
        (r.page, r.reason) for r in results if r.outcome is not Outcome.DRAWN
    ]
