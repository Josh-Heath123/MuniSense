"""A copy of the committed data for each test (P2-11, P2-12), with the fixture drafts.

The committed publications are left out: each test publishes the drafts itself.
"""

import os
import shutil
from pathlib import Path

import pytest

from support.publishing import DRAFTS, ROOT


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of the committed data for the module; tests link to it."""
    target = tmp_path_factory.mktemp("base") / "data"
    for part in ("catalogue", "sources"):
        shutil.copytree(ROOT / "data" / part, target / part)
    shutil.copytree(DRAFTS, target / "drafts")
    return target


@pytest.fixture
def data(base: Path, tmp_path: Path) -> Path:
    """A test's own data folder: hard links to the shared copy (regular files, same bytes).

    A test that changes a file replaces it (unlink, then write), never writes through a link.
    """
    target = tmp_path / "data"
    shutil.copytree(base, target, copy_function=os.link)
    return target
