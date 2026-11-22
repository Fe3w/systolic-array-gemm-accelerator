"""Smoke test: the README figures regenerate from their script and the committed CSVs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("readme_figures.py")


def test_readme_figures_regenerate(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)], check=True,
                   capture_output=True)  # fmt: skip
    for name in ("architecture.png", "flow.png", "utilization_before_after.png"):
        assert (tmp_path / name).stat().st_size > 10_000, name
