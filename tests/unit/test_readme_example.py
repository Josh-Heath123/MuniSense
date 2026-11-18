"""P1-17: the README's example bill is the engine's own output.

The block between `<!-- demo:start -->` and `<!-- demo:end -->` in README.md must equal
what `uv run poe demo` prints, so the README cannot drift from the code or the data.
"""

import runpy
from decimal import Decimal
from pathlib import Path

import pytest

from munisense.services import demo

README = Path(__file__).resolve().parents[2] / "README.md"


def _readme_block() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("<!-- demo:start -->\n") + len("<!-- demo:start -->\n")
    end = text.index("\n<!-- demo:end -->")
    return text[start:end]


def test_the_readme_example_is_the_engine_output() -> None:
    assert _readme_block() == demo.render(demo.example_bill())


def test_the_example_is_the_hand_checked_tariff_b_bill() -> None:
    # P1-9's hand calculation: basic 109.78 + energy 350 x 3.3700 = 1179.50; subtotal
    # 1289.28; VAT 15% = 193.392 -> 193.39; total 1482.67.
    bill = demo.example_bill()
    assert bill.total.rand == Decimal("1482.67")
    assert bill.vat.rand == Decimal("193.39")


def test_poe_demo_prints_the_example(capsys: pytest.CaptureFixture[str]) -> None:
    demo.main()
    assert capsys.readouterr().out.rstrip("\n") == _readme_block()


# runpy warns because the test module already imported demo; re-running it is the point.
@pytest.mark.filterwarnings("ignore:.*found in sys.modules after import of package:RuntimeWarning")
def test_the_module_runs_as_a_script(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_module("munisense.services.demo", run_name="__main__")
    assert capsys.readouterr().out.startswith("TARIFF B (RESIDENTIAL)")


@pytest.mark.parametrize(
    ("code", "phase"),
    [
        ("b-residential-1-phase", "single-phase"),
        ("b-residential-3-phase", "three-phase"),
        ("other", "other"),
    ],
)
def test_the_heading_names_the_supply_phase_from_the_tariff_code(code: str, phase: str) -> None:
    assert demo._phase(code) == phase  # a module-level helper of the demo
