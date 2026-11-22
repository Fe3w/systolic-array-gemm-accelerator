"""Smoke test: the architecture figures regenerate from their script (M14)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("figures.py")


def test_figures_regenerate(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)], check=True,
                   capture_output=True)  # fmt: skip
    for name in ("block_diagram.png", "dataflow_s4.png"):
        assert (tmp_path / name).stat().st_size > 10_000, name
