"""The Homeflex 2026/27 drafts (P4-13), read from their fixture copies, never from
`data/drafts/` (E62): the publication pull request deletes the drafts without touching code.

The real citation check runs on every citation; the values themselves are only `estimated`
until the owner's hand check.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from munisense.domain.citations import Estimated, iter_cited
from munisense.domain.money import Rate
from munisense.domain.tariffs import (
    ExportCredit,
    FixedCharge,
    FlatEnergy,
    TariffVersion,
    TimeOfUseEnergy,
)
from munisense.domain.tariffs.time_of_use import TimeRange
from munisense.ingestion.citation_check import Outcome, check_citations
from munisense.ingestion.publish import documents, text_check_reasons
from munisense.provenance.drafts import load_file
from support.publishing import DRAFTS

ROOT = Path(__file__).resolve().parents[3]
HOMEFLEX = sorted((DRAFTS / "eskom-direct" / "2026-27").glob("homeflex-*.json"))


def _version(path: Path) -> TariffVersion:
    return load_file(path, TariffVersion)


def test_there_are_four_homeflex_drafts() -> None:
    assert [p.stem for p in HOMEFLEX] == [f"homeflex-{n}" for n in (1, 2, 3, 4)]


@pytest.mark.parametrize("path", HOMEFLEX, ids=lambda p: p.stem)
def test_every_value_is_estimated_until_the_hand_check(path: Path) -> None:
    version = _version(path)
    assert all(isinstance(c.status, Estimated) for _, c in iter_cited(version))
    assert isinstance(version.billing_policy.status, Estimated)
    assert isinstance(version.rounding_policy.status, Estimated)


@pytest.mark.parametrize("path", HOMEFLEX, ids=lambda p: p.stem)
def test_the_components_are_those_the_sources_list(path: Path) -> None:
    """Book PDF page 28: TOU energy, legacy, network demand and ancillary (c/kWh); service and
    administration, network capacity and generation capacity (R/POD/day); page 43: the
    Gen-offset energy credit, the only Gen-offset item the summaries list for Homeflex."""
    kinds = [(c.name, type(c)) for c in _version(path).components]
    assert kinds == [
        ("active_energy", TimeOfUseEnergy),
        ("legacy", FlatEnergy),
        ("network_demand", FlatEnergy),
        ("ancillary_service", FlatEnergy),
        ("service_and_administration", FixedCharge),
        ("network_capacity", FixedCharge),
        ("generation_capacity", FixedCharge),
        ("gen_offset_credit", ExportCredit),
    ]


@pytest.mark.parametrize("path", HOMEFLEX, ids=lambda p: p.stem)
def test_no_credit_rate_is_above_its_energy_rate(path: Path) -> None:
    """A credit above the energy rate would be allowed but likely a typo (P4-8 review)."""
    version = _version(path)
    energy, credit = version.components[0], version.components[-1]
    assert isinstance(energy, TimeOfUseEnergy)
    assert isinstance(credit, ExportCredit)
    for rate in credit.rates:
        charged = energy.rate_for(rate.season, rate.period).value.value
        assert rate.rate.value.value <= charged


def test_the_drafts_differ_only_in_name_size_and_capacity_charges() -> None:
    """Everything but the tariff code, printed name, supply size and the two capacity
    charges is the same in all four; those differ in each."""
    differ = {"tariff_code", "printed_name", "applies_to"}
    dumps = [_version(path).model_dump(mode="json") for path in HOMEFLEX]
    for dump in dumps[1:]:
        assert {k: v for k, v in dump.items() if k not in differ | {"components"}} == {
            k: v for k, v in dumps[0].items() if k not in differ | {"components"}
        }
        same = [c for n, c in enumerate(dump["components"]) if n not in (5, 6)]
        assert same == [c for n, c in enumerate(dumps[0]["components"]) if n not in (5, 6)]
    for name in (5, 6):
        rates = [d["components"][name]["rate"]["value"]["value"] for d in dumps]
        assert len(set(rates)) == 4, rates
    assert [d["components"][5]["rate"]["value"]["value"] for d in dumps] == [
        "13.19",
        "29.44",
        "62.89",
        "9.08",
    ]
    assert [d["components"][6]["rate"]["value"]["value"] for d in dumps] == [
        "1.09",
        "1.93",
        "4.70",
        "0.71",
    ]


FIGURE = re.compile(r"[0-9]+[.,][0-9]{2}")


@pytest.mark.parametrize("path", HOMEFLEX, ids=lambda p: p.stem)
def test_each_rate_is_the_first_figure_of_its_text_and_the_second_includes_vat(
    path: Path,
) -> None:
    """The citation check finds the text on the page; this ties the value to the text: the
    first figure is the value, and the second (where printed) is it with 15% VAT, rounded
    half up ("R0,82" read as 0.82)."""
    checked = 0
    for _, cited in iter_cited(_version(path)):
        if not isinstance(cited.value, Rate):
            continue
        figures = [
            Decimal(f.replace(",", ".")) for f in FIGURE.findall(cited.citation.printed_text)
        ]
        assert figures[0] == cited.value.value, cited.citation.printed_text
        if len(figures) > 1:
            with_vat = (cited.value.value * Decimal("1.15")).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            assert figures[1] == with_vat, cited.citation.printed_text
        checked += 1
    assert checked == 18  # 6 energy, 6 credit, 3 flat energy and 3 fixed-charge rates


@pytest.mark.parametrize("path", HOMEFLEX, ids=lambda p: p.stem)
def test_each_drawn_range_is_cited_once_and_adjacent_ranges_differ(path: Path) -> None:
    """The adjacent-range decision (P4-13): every range has its own transcription, cited by
    no other range, and two ranges next to each other in a day never share a period. The
    off-peak arc across midnight (for example 22 to 6) is two ranges, 22 to 24 and 0 to 6,
    each with its own transcription."""
    calendar = _version(path).tou_calendar
    assert calendar is not None
    texts = [r.citation.printed_text for s in calendar.schedules for r in s.ranges]
    assert len(texts) == len(set(texts)) == 29
    for schedule in calendar.schedules:
        ranges: list[TimeRange] = [r.value for r in schedule.ranges]
        for before, after in pairwise(ranges):
            assert before.period != after.period, (schedule.season, schedule.day_type)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("path", "passed", "drawn"),
    [(HOMEFLEX[0], 44, 29), (HOMEFLEX[1], 44, 29), (HOMEFLEX[2], 43, 30), (HOMEFLEX[3], 44, 29)],
    ids=lambda v: v.stem if isinstance(v, Path) else str(v),
)
def test_every_citation_passes_the_real_check(path: Path, passed: int, drawn: int) -> None:
    """The calendar's 29 ranges are drawn (book page 45); Homeflex 3's network capacity
    charge is drawn too (schedule page 33, the proposed reading of R62.89)."""
    version = _version(path)
    results = check_citations(version, documents(ROOT / "data"))
    outcomes = [r.outcome for r in results]
    assert (outcomes.count(Outcome.PASSED), outcomes.count(Outcome.DRAWN)) == (passed, drawn), [
        (r.path, r.reason) for r in results if r.outcome is Outcome.FAILED
    ]
    assert text_check_reasons(version, results) == []


def test_homeflex_3_carries_the_schedules_figure_until_the_owner_decides() -> None:
    capacity = _version(HOMEFLEX[2]).components[5]
    assert isinstance(capacity, FixedCharge)
    assert capacity.rate.value.value == Decimal("62.89")
    assert capacity.rate.citation.drawn is True
    assert isinstance(capacity.rate.status, Estimated)
    assert "R52.89" in capacity.rate.status.reason
