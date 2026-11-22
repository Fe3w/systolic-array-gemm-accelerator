"""Every results/ file named after a commit must point at a commit that exists (M11b, issue 17).

Milestone PRs are squash-merged, so the producing commit lives on the milestone
branch (D-018); docs/RESULTS.md maps each file to branch, PR and squash commit.
This test fails if a referenced commit is missing (e.g. a branch was deleted).
The published copy of the repository starts a fresh history (D-034), so there
the commit check is skipped; the index check still runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The publishing kit (.publish/) exists only in the development repository.
DEV_REPO = (REPO / ".publish").is_dir()
# <name>_<sha>[-dirty][_<option>...].csv|json; options: seed2, quick, 20ns, io30, hold0p25 ...
SHA = re.compile(r"_([0-9a-f]{7})(?:-dirty)?(?:_[a-z0-9]+)*\.(?:csv|json)$")


def _result_shas() -> dict[str, list[str]]:
    shas: dict[str, list[str]] = {}
    for f in sorted((REPO / "results").rglob("*")):
        m = SHA.search(f.name) or re.match(r"([0-9a-f]{7})\.csv$", f.name)
        if m:
            shas.setdefault(m.group(1), []).append(str(f.relative_to(REPO)))
    return shas


def _has_commit(sha: str) -> bool:
    r = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO,
                       capture_output=True)  # fmt: skip
    return r.returncode == 0


def test_results_are_named_after_commits() -> None:
    assert _result_shas(), "no result files found"


@pytest.mark.parametrize("sha", sorted(_result_shas()))
def test_producing_commit_exists(sha: str) -> None:
    if not DEV_REPO:
        pytest.skip("published copy: results name commits of the development repository (D-034)")
    if subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO,
                      capture_output=True, text=True).stdout.strip() == "true":  # fmt: skip
        pytest.skip("shallow clone: history not available")
    assert _has_commit(sha), f"commit {sha} (for {_result_shas()[sha]}) is not in the repository"


def test_index_lists_every_commit() -> None:
    index = (REPO / "docs" / "RESULTS.md").read_text()
    missing = [s for s in _result_shas() if s not in index]
    assert not missing, f"docs/RESULTS.md does not mention {missing}"


@pytest.mark.parametrize(("name", "sha"), [
    ("sa_core_S8_c64045a_seed2.json", "c64045a"),
    ("latency_d4aedec.csv", "d4aedec"),
    ("sa_array_S8_f1981ab_20ns.json", "f1981ab"),
    ("sa_array_S8_cc4aee5_15ns_hold0p25.json", "cc4aee5"),
    ("sa_array_S8_0d8ca14_15ns_io30.json", "0d8ca14"),
])  # fmt: skip
def test_name_pattern(name: str, sha: str) -> None:
    """M12: ASIC result names carry run options after the commit."""
    m = SHA.search(name)
    assert m and m.group(1) == sha
