"""P1-17, P2-13: the README's example bill is the engine's own output from published data.

The block between `<!-- demo:start -->` and `<!-- demo:end -->` in README.md must equal
what `uv run poe demo` prints. The test database is rebuilt from the committed files
themselves (`data/`, read only), so the README cannot drift from the code, the published
data or the path through the repository.
"""

import os
import runpy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from munisense.domain.citations import StatusKind
from munisense.persistence.loader import rebuild
from munisense.platform.settings import LOCAL_DEFAULTS
from munisense.services import demo
from support.database import TestDatabase

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
NOW = datetime(2026, 12, 1, tzinfo=UTC)  # after the P2-13 publications
BEFORE = datetime(2026, 11, 20, tzinfo=UTC)  # before them: nothing recorded yet


def _readme_block() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("<!-- demo:start -->\n") + len("<!-- demo:start -->\n")
    end = text.index("\n<!-- demo:end -->")
    return text[start:end]


@pytest.fixture
def loaded(test_database: TestDatabase) -> TestDatabase:
    """The test database rebuilt from the committed publications."""
    summary = rebuild(ROOT / "data", test_database.migration)
    assert (summary.publications, summary.tariff_versions, summary.vat_rates) == (3, 2, 1)
    return test_database


def _env() -> dict[str, str]:
    """The demo's setting, pointed at the test database as the application role."""
    name = "MUNISENSE_TEST_DATABASE_URL"
    return {"MUNISENSE_DATABASE_URL": os.environ.get(name, LOCAL_DEFAULTS[name])}


def test_the_readme_example_is_the_engine_output(loaded: TestDatabase) -> None:
    assert _readme_block() == demo.render(demo.example_bill(loaded.app, NOW))


def test_the_example_is_the_hand_checked_tariff_b_bill(loaded: TestDatabase) -> None:
    # P1-9's hand calculation: basic 109.78 + energy 350 x 3.3700 = 1179.50; subtotal
    # 1289.28; VAT 15% = 193.392 -> 193.39; total 1482.67.
    bill = demo.example_bill(loaded.app, NOW)
    assert bill.total.rand == Decimal("1482.67")
    assert bill.vat.rand == Decimal("193.39")
    # VAT treatment and season dates stay estimated (E56), so the bill does too.
    assert bill.status is StatusKind.ESTIMATED


def test_poe_demo_prints_the_example(
    loaded: TestDatabase, capsys: pytest.CaptureFixture[str]
) -> None:
    assert demo.main(_env(), lambda: NOW) == 0
    assert capsys.readouterr().out.rstrip("\n") == _readme_block()


def test_the_demo_says_what_to_run_when_nothing_is_recorded(
    loaded: TestDatabase, capsys: pytest.CaptureFixture[str]
) -> None:
    assert demo.main(_env(), lambda: BEFORE) == 1
    error = capsys.readouterr().err
    assert "no version of city-of-ekurhuleni/b-residential-1-phase" in error
    assert "uv run poe db-rebuild" in error


# runpy warns because the test module already imported demo; re-running it is the point.
@pytest.mark.filterwarnings("ignore:.*found in sys.modules after import of package:RuntimeWarning")
def test_the_module_runs_as_a_script(
    loaded: TestDatabase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in _env().items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_module("munisense.services.demo", run_name="__main__")
    assert exit_.value.code == 0
    assert capsys.readouterr().out.startswith("TARIFF B (RESIDENTIAL)")
