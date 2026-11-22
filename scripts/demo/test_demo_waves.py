"""`make demo-waves` smoke test (M15): VCD produced, every signal of the saved layout in it."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_demo_waves_vcd_matches_layout() -> None:
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "demo" / "demo_waves.py"),
                          "--no-open"], cwd=REPO, capture_output=True, text=True,
                         timeout=900)  # fmt: skip
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    vcd = (REPO / "build" / "demo" / "tile_s4.vcd").read_text()
    names = set()
    scope: list[str] = []
    for line in vcd.splitlines():
        s = line.strip()
        if s.startswith("$scope"):
            scope.append(s.split()[2])
        elif s.startswith("$upscope"):
            scope.pop()
        elif s.startswith("$var"):
            p = s.split()
            names.add(".".join([*scope, p[4]]))
        elif s.startswith("$enddefinitions"):
            break
    layout = (REPO / "docs" / "demo" / "tile_s4.gtkw").read_text()
    wanted = [re.sub(r"\[\d+:0\]$", "", line) for line in layout.splitlines()
              if line.startswith("sa_array.")]  # fmt: skip
    assert len(wanted) == 21
    missing = [w for w in wanted if w not in names]
    assert not missing, missing
