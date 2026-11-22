"""Smoke test (M15): the tile animation renders from the demo-waves VCD."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]


def test_animation_renders(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(REPO / "scripts" / "demo" / "demo_waves.py"), "--no-open"],
                   cwd=REPO, check=True, capture_output=True, timeout=900)  # fmt: skip
    gif = tmp_path / "tile.gif"
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "report" / "animate_tile.py"),
                          str(REPO / "build" / "demo" / "tile_s4.vcd"), "--out", str(gif)],
                         capture_output=True, text=True, timeout=300)  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    with Image.open(gif) as im:
        # 4 weight-load cycles + 4 rows + 2S latency + 4 output rows, plus the edges
        assert im.n_frames >= 16
