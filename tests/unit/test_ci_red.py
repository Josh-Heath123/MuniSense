"""Temporary: proves CI fails on a failing test. Reverted in the next commit."""


def test_ci_must_fail() -> None:
    assert 1 == 2
