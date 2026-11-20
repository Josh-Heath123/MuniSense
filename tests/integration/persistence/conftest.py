"""A copy of the committed data for each test (P2-11, P2-12)."""

import os
import shutil
from pathlib import Path

import pytest

from support.publishing import ROOT


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of the committed data for the module; tests link to it."""
    target = tmp_path_factory.mktemp("base") / "data"
    for part in ("catalogue", "sources", "drafts"):
        shutil.copytree(ROOT / "data" / part, target / part)
    return target


@pytest.fixture
def data(base: Path, tmp_path: Path) -> Path:
    """A test's own data folder: hard links to the shared copy (regular files, same bytes).

    A test that changes a file replaces it (unlink, then write), never writes through a link.
    """
    target = tmp_path / "data"
    shutil.copytree(base, target, copy_function=os.link)
    return target
