"""The demo's refusals and helpers that need no database (P2-13).

The README example itself is checked against the database in
`tests/integration/test_readme_example.py`.
"""

import os
from collections.abc import Callable

import pytest

from munisense.domain.billing import Bill
from munisense.persistence.connection import DatabaseNotReadyError
from munisense.services import demo


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


def test_unsafe_settings_are_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main({"MUNISENSE_ENVIRONMENT": "elsewhere"}) == 2
    assert capsys.readouterr().err.startswith("demo: MUNISENSE_ENVIRONMENT must be")


@pytest.fixture
def no_libpq_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """libpq reads the real process environment, so the engine checks it, not `env`."""
    for name in [n for n in os.environ if n.startswith("PG")]:
        monkeypatch.delenv(name)


@pytest.mark.usefixtures("no_libpq_environment")
def test_an_unreachable_database_says_how_to_start_it(capsys: pytest.CaptureFixture[str]) -> None:
    # Port 1 on loopback: nothing listens, so the connection is refused at once.
    url = "postgresql://munisense_app:munisense-app-local-only@127.0.0.1:1/munisense_dev"
    assert demo.main({"MUNISENSE_DATABASE_URL": url}) == 1
    error = capsys.readouterr().err
    assert error == (
        "demo: cannot connect to the database 'munisense_dev'; is it running"
        " (`docker compose up -d db`), and do the MUNISENSE_DATABASE_URL settings match it?\n"
    )
    assert "local-only" not in error  # never the password


def _raising(error: Exception) -> Callable[..., Bill]:
    def example_bill(*_: object) -> Bill:
        raise error

    return example_bill


def test_a_database_without_tables_says_what_to_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "example_bill", _raising(DatabaseNotReadyError("no tables")))
    assert demo.main({}) == 1
    assert capsys.readouterr().err == (
        "demo: no tables; run `uv run poe db-bootstrap` once, then `uv run poe db-rebuild`\n"
    )
