"""Test (M15): the GTKWave screenshot of one S = 4 tile renders, or the script
says exactly what is missing when gtkwave / Xvfb / ImageMagick are not installed."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
TOOLS = ("gtkwave", "Xvfb", "import", "convert")


def test_screenshot(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(REPO / "scripts" / "demo" / "demo_waves.py"), "--no-open"],
                   cwd=REPO, check=True, capture_output=True, timeout=900)  # fmt: skip
    png = tmp_path / "waves.png"
    script = REPO / "scripts" / "waves" / "gtkwave_screenshot.py"
    out = subprocess.run([sys.executable, str(script), "--out", str(png)],
                         capture_output=True, text=True, timeout=120)  # fmt: skip
    if all(shutil.which(t) for t in TOOLS):
        assert out.returncode == 0, out.stdout + out.stderr[-2000:]
        with Image.open(png) as im:
            assert im.size == (1345, 570)
            # traces are drawn: plenty of GTKWave's green on the black wave pane
            px = np.asarray(im.convert("RGB")).astype(int)
            green = int(((px[..., 1] > 150) & (px[..., 0] < 100)).sum())
            assert green > 2000
    else:
        assert out.returncode == 1
        assert "missing" in out.stdout and "sudo apt install" in out.stdout
