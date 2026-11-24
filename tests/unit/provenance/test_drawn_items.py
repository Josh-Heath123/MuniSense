"""The `drawn` shapes (P4-11, ADR-0016 point 5): the manifest's drawn list, a citation's
`drawn` flag, the `drawn` text check and the envelope's `drawn` count. Each new field is
omitted when absent, so files written before it are unchanged (ADR-0016 point 3)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from munisense.domain.citations import Citation, TextCheck, Verified, normalise_whitespace
from munisense.provenance.publication import CitationCheckCounts
from munisense.provenance.sources import (
    MAX_DRAWN_ITEMS,
    MAX_DRAWN_TEXTS,
    SourceDocument,
    SourceManifest,
)

ROOT = Path(__file__).resolve().parents[3]
SARS: dict[str, Any] = json.loads((ROOT / "data/sources/sars/sources.json").read_text("utf-8"))
SHA = "a" * 64


def _document(**changes: object) -> dict[str, Any]:
    document = {k: v for k, v in SARS["documents"][0].items() if k != "drawn"}
    return {**document, "text_layer": True, **changes}


def _item(page: int = 2, *texts: str) -> dict[str, object]:
    return {"page": page, "what": "a drawn figure", "texts": list(texts or ("Peak 6 to 8",))}


# --- the manifest's drawn list ---------------------------------------------------------


def test_a_document_without_drawn_items_writes_no_drawn_key() -> None:
    document = SourceDocument.model_validate_json(json.dumps(_document()))
    assert document.drawn is None
    assert "drawn" not in json.loads(document.model_dump_json())


def test_every_committed_manifest_round_trips_byte_for_byte() -> None:
    for path in sorted((ROOT / "data/sources").glob("*/sources.json")):
        manifest = SourceManifest.model_validate_json(path.read_bytes())
        assert json.loads(manifest.model_dump_json()) == json.loads(path.read_text("utf-8"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"text_layer": False, "drawn": [_item()]}, "only for a document with a text layer"),
        ({"drawn": [_item(page=10_000)]}, "past the document's"),
        ({"drawn": []}, "at least 1 item"),
        ({"drawn": [{**_item(), "texts": []}]}, "at least 1 item"),
        ({"drawn": [{**_item(), "what": " "}]}, "at least 1 character"),
        ({"drawn": [_item(2, "Peak 6 to 8", " Peak  6\nto 8 ")]}, "listed twice"),
        ({"drawn": [_item(2, "Peak 6 to 8"), _item(2, "Peak 6 to 8")]}, "listed twice"),
        ({"drawn": [_item(0)]}, "greater than or equal to 1"),
        ({"drawn": [_item()] * (MAX_DRAWN_ITEMS + 1)}, f"at most {MAX_DRAWN_ITEMS} items"),
        (
            {"drawn": [_item(2, *(f"t{n}" for n in range(MAX_DRAWN_TEXTS + 1)))]},
            f"at most {MAX_DRAWN_TEXTS} items",
        ),
        ({"drawn": [_item(2, "a\x1bb")]}, "control characters"),
        ({"drawn": [{**_item(), "extra": 1}]}, "Extra inputs are not permitted"),
    ],
)
def test_a_drawn_list_is_refused_when_it_cannot_be_trusted(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SourceDocument.model_validate_json(json.dumps(_document(**changes)))


def test_the_same_text_may_be_drawn_on_two_pages() -> None:
    document = SourceDocument.model_validate_json(
        json.dumps(_document(drawn=[_item(2, "Peak 6 to 8"), _item(3, "Peak 6 to 8")]))
    )
    assert document.drawn_texts(2) == document.drawn_texts(3) == {"Peak 6 to 8"}


def test_drawn_texts_are_per_page_and_whitespace_normalised() -> None:
    document = SourceDocument.model_validate_json(
        json.dumps(
            _document(drawn=[_item(2, " Peak  6\nto 8 ", "Standard 8 to 17"), _item(3, "x")])
        )
    )
    assert document.drawn_texts(2) == {"Peak 6 to 8", "Standard 8 to 17"}
    assert document.drawn_texts(3) == {"x"}
    assert document.drawn_texts(4) == frozenset()


# --- a citation's drawn flag -----------------------------------------------------------


def _citation(**changes: object) -> dict[str, object]:
    return {"document_sha256": SHA, "page": 2, "locator": "Figure 2", "printed_text": "x"} | changes


def test_a_citation_is_not_drawn_unless_it_says_so_and_then_writes_no_key() -> None:
    citation = Citation.model_validate_json(json.dumps(_citation()))
    assert citation.drawn is None
    assert "drawn" not in json.loads(citation.model_dump_json())


def test_a_drawn_citation_round_trips() -> None:
    citation = Citation.model_validate_json(json.dumps(_citation(drawn=True)))
    assert citation.drawn is True
    assert Citation.model_validate_json(citation.model_dump_json()) == citation


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_drawn_is_only_ever_true(value: object) -> None:
    """One way to say "drawn": `true`. Not drawn is the key left out (`null`, the default,
    is accepted and written as no key)."""
    if value is None:
        # The model's default: accepted, and written as no key.
        assert Citation.model_validate_json(json.dumps(_citation(drawn=value))).drawn is None
        return
    with pytest.raises(ValidationError, match="drawn"):
        Citation.model_validate_json(json.dumps(_citation(drawn=value)))


def test_verified_accepts_the_drawn_text_check() -> None:
    status = Verified.model_validate_json(
        json.dumps(
            {
                "verifier": "owner",
                "verifier_kind": "human",
                "method": "visual comparison with the source page",
                "verified_on": "2026-12-01",
                "text_check": "drawn",
            }
        )
    )
    assert status.text_check is TextCheck.DRAWN


def test_the_whitespace_rule_is_the_citation_checks() -> None:
    assert normalise_whitespace("  Peak\t6\nto" + chr(0xA0) + "8 ") == "Peak 6 to 8"


# --- the envelope's drawn count --------------------------------------------------------


def test_a_count_without_drawn_writes_no_drawn_key() -> None:
    counts = CitationCheckCounts.model_validate_json(
        '{"passed": 1, "no_text_layer": 0, "failed": 0}'
    )
    assert counts.drawn is None
    assert json.loads(counts.model_dump_json()) == {"passed": 1, "no_text_layer": 0, "failed": 0}


def test_a_drawn_count_of_zero_is_written() -> None:
    counts = CitationCheckCounts.model_validate_json(
        '{"passed": 1, "no_text_layer": 0, "drawn": 0, "failed": 0}'
    )
    assert json.loads(counts.model_dump_json()) == {
        "passed": 1,
        "no_text_layer": 0,
        "drawn": 0,
        "failed": 0,
    }


def test_a_negative_drawn_count_is_refused() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        CitationCheckCounts.model_validate_json(
            '{"passed": 1, "no_text_layer": 0, "drawn": -1, "failed": 0}'
        )
