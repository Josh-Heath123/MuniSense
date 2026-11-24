"""The Homeflex 2026/27 drafts (P4-13), read from their fixture copies, never from
`data/drafts/` (E62): the publication pull request deletes the drafts without touching code.

The real citation check runs on every citation; the values themselves are only `estimated`
until the owner's hand check.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from munisense.domain.citations import Estimated, iter_cited
from munisense.domain.tariffs import (
    ExportCredit,
    FixedCharge,
    FlatEnergy,
    TariffVersion,
    TimeOfUseEnergy,
)
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
    first = _version(HOMEFLEX[0])
    for path in HOMEFLEX[1:]:
        other = _version(path)
        assert other.components[:5] == first.components[:5]
        assert other.components[-1] == first.components[-1]
        assert other.tou_calendar == first.tou_calendar
        assert other.billing_policy == first.billing_policy


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
