"""Temporary: proves a failing test turns CI red. Removed in the next commit."""


def test_ci_must_fail() -> None:
    assert sum([1]) == 2
