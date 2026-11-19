"""The bootstrap refuses before connecting when it may not run (P2-3)."""

import pytest

from munisense.persistence.bootstrap import main


def test_it_refuses_outside_a_local_environment(capsys: pytest.CaptureFixture[str]) -> None:
    assert main({"MUNISENSE_ENVIRONMENT": "deployed"}) == 2
    assert "only in a local environment" in capsys.readouterr().err


def test_it_refuses_unsafe_settings(capsys: pytest.CaptureFixture[str]) -> None:
    assert main({"PGSERVICE": "munisense"}) == 2
    assert "db-bootstrap: PGSERVICE is set" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy: the module is already imported
def test_its_command_exits_with_the_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy

    monkeypatch.setenv("MUNISENSE_ENVIRONMENT", "deployed")
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("munisense.persistence.bootstrap", run_name="__main__")
    assert exited.value.code == 2
