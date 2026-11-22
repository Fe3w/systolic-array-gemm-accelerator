"""docs/RESULTS_SUMMARY.md is generated from results/ and must not drift (M14)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_path = Path(__file__).with_name("results_summary.py")
_spec = importlib.util.spec_from_file_location("results_summary", _path)
assert _spec and _spec.loader
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def test_committed_summary_is_current() -> None:
    committed = (REPO / "docs" / "RESULTS_SUMMARY.md").read_text()
    assert committed == rs.render(REPO / "results"), (
        "docs/RESULTS_SUMMARY.md is stale: run python3 scripts/report/results_summary.py"
    )


def test_every_result_file_is_cited() -> None:
    """Each summary JSON/CSV in results/ (not raw/ or tool inputs) appears in the summary."""
    text = rs.render(REPO / "results")
    for f in rs.result_files(REPO / "results"):
        assert str(f.relative_to(REPO)) in text, f"{f} missing from the summary"


def test_numbers_come_from_files() -> None:
    """Spot check: the clean SKY130 run's slack appears exactly as stored."""
    text = rs.render(REPO / "results")
    assert "+0.351" in text and "1.053" in text
    assert "12,787" in text  # max-slew violations are shown, not hidden
