"""Settings for every test: Hypothesis's storage and profile (W19, E51; E43).

Hypothesis keeps all of its storage (saved examples, constants, Unicode data) in one home
folder, which moves off the `/mnt/c` disk to `~/.cache/munisense/hypothesis`, whatever runs
pytest. The profile applies to every Hypothesis test, wherever it sits.
"""

from pathlib import Path

from hypothesis import settings
from hypothesis.configuration import set_hypothesis_home_dir

set_hypothesis_home_dir(Path.home() / ".cache" / "munisense" / "hypothesis")

# A generous per-example deadline (2 s instead of Hypothesis's 200 ms): on a loaded machine
# (the owner's WSL disk, a slow CI runner) 200 ms can fail for timing, not correctness. One
# full run on 2026-11-19 failed once while taking 191 s instead of the usual 35-70 s; the
# failing test was not captured, so the cause is not proven. A test slower than 2 s per
# example still fails.
settings.register_profile("munisense", deadline=2000)
settings.load_profile("munisense")
