#!/usr/bin/env python3
"""`make demo-waves`: waveform of one S = 4 tile in GTKWave (M15).

Runs the sa_array testbench at S = 4 with waves on (seed 5; its first test
loads identity weights and streams 3 rows), copies the VCD to
build/demo/tile_s4.vcd and opens it with the saved layout docs/demo/tile_s4.gtkw:
weight load (w_load, w_row, weights of column 0), activations before and after
the skew (a_row, grid_a_valid, a_q of column 0), partial sums down column 0,
and the de-skewed outputs (grid_valid, c_valid, c_row). Markers sit at the
first w_load (15 ns) and the first c_valid (130 ns).
Usage: python3 scripts/demo/demo_waves.py [--no-open]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "compiler")]

from tb.common.runner import build_dir_for  # noqa: E402

VCD = REPO / "build" / "demo" / "tile_s4.vcd"
LAYOUT = REPO / "docs" / "demo" / "tile_s4.gtkw"
TEST = "tb/array/test_array.py::test_sa_array[4-False]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true", help="only produce the VCD")
    args = ap.parse_args()
    env = {**os.environ, "SYSARRAY_WAVES": "1", "SYSARRAY_SEED": "5"}
    src = build_dir_for(REPO / "tb" / "array", "sa_array", {"S": 4, "DATA_W": 8, "ACC_W": 32})
    (src / "dump.vcd").unlink(missing_ok=True)  # never copy a stale waveform
    print(f"running {TEST} with waves (seed 5) ...", flush=True)
    log = REPO / "build" / "demo" / "demo_waves_sim.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w") as f:
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", TEST], cwd=REPO, env=env,
                            stdout=f, stderr=subprocess.STDOUT).returncode  # fmt: skip
    if rc != 0:
        print(f"simulation failed; log: {log.relative_to(REPO)}")
        print("check the tools first: make check (Verilator must be >= 5.036)")
        return 1
    shutil.copy(src / "dump.vcd", VCD)
    cmd = ["gtkwave", str(VCD.relative_to(REPO)), str(LAYOUT.relative_to(REPO))]
    print(f"VCD: {VCD.relative_to(REPO)}  layout: {LAYOUT.relative_to(REPO)}")
    if args.no_open:
        print("open with: " + " ".join(cmd))
        return 0
    if not shutil.which("gtkwave"):
        print("gtkwave not found (Ubuntu: sudo apt install gtkwave); then run: " + " ".join(cmd))
        return 0
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("no display; on a desktop run: " + " ".join(cmd))
        return 0
    subprocess.Popen(cmd, cwd=REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
