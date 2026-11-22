#!/usr/bin/env python3
"""Screenshot of the `make demo-waves` waveform in GTKWave -> docs/img/waves_tile_s4.png.

Runs GTKWave on build/demo/tile_s4.vcd with the committed layout
docs/demo/tile_s4.gtkw (hierarchy pane hidden) inside a virtual X display
(Xvfb), grabs the window with ImageMagick `import` and crops the picture to
the Signals and Waves panes. The picture is the real simulator waveform, the
same one `make demo-waves` opens on a desktop.

Needs: gtkwave, Xvfb, ImageMagick (Ubuntu: sudo apt install gtkwave xvfb imagemagick).
Usage (repo root, after `python3 scripts/demo/demo_waves.py --no-open`):
    python3 scripts/waves/gtkwave_screenshot.py [--out docs/img/waves_tile_s4.png]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VCD = REPO / "build" / "demo" / "tile_s4.vcd"
LAYOUT = REPO / "docs" / "demo" / "tile_s4.gtkw"
W, H = 1600, 900
# Keep only the Signals and Waves panes: x from 255 (right of the collapsed
# hierarchy pane), y from 100 (below the toolbar) to 670 (below the last trace).
CROP = "1345x570+255+100"
DISPLAY = ":97"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "docs" / "img" / "waves_tile_s4.png"))
    args = ap.parse_args()
    missing = [t for t in ("gtkwave", "Xvfb", "import", "convert") if not shutil.which(t)]
    if missing:
        print(f"gtkwave_screenshot: missing {', '.join(missing)} "
              "(Ubuntu: sudo apt install gtkwave xvfb imagemagick)")  # fmt: skip
        return 1
    if not VCD.exists():
        print(f"gtkwave_screenshot: {VCD.relative_to(REPO)} not found; "
              "run: python3 scripts/demo/demo_waves.py --no-open")  # fmt: skip
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        layout = Path(tmp) / "shot.gtkw"
        text = LAYOUT.read_text().replace("[sst_expanded] 1", "[sst_expanded] 0")
        layout.write_text(text)
        raw = Path(tmp) / "raw.png"
        xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{W}x{H}x24"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        gtk = None
        try:
            time.sleep(1.0)
            env = {**os.environ, "DISPLAY": DISPLAY}
            cmd = ["gtkwave", str(VCD.relative_to(REPO)), str(layout)]
            gtk = subprocess.Popen(cmd, env=env, cwd=REPO, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)  # fmt: skip
            time.sleep(6.0)  # let GTKWave load the VCD and draw the traces
            subprocess.run(["import", "-window", "root", str(raw)], env=env, check=True)
        finally:
            if gtk:
                gtk.terminate()
            xvfb.terminate()
        subprocess.run(["convert", str(raw), "-crop", CROP, "+repage", str(out)],
                       check=True)  # fmt: skip
    print(f"gtkwave_screenshot: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
