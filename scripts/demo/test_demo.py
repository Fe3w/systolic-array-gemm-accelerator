"""`make demo` smoke test (M15): a small GEMM through the demo script end to end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_demo_small_shape() -> None:
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "demo" / "demo.py"),
                          "--M", "8", "--N", "8", "--K", "16"],
                         cwd=REPO, capture_output=True, text=True, timeout=900)  # fmt: skip
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "predicted (analytical, sysarray.predict)" in out.stdout
    assert "C matches NumPy: yes" in out.stdout
    assert "measured == predicted: yes" in out.stdout
