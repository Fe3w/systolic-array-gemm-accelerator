#!/usr/bin/env python3
"""`make demo`: one GEMM, compiled, predicted, run on the RTL and checked (M15).

Default shape: M = 128, N = 64, K = 768, one BERT-base attention head's Q
projection for a 128-token sequence (768 -> 64). Steps:
  1. compile C = A·B (random int8) to sa_top commands with sysarray.tile();
  2. predict the cycle count with sysarray.predict() before simulating;
  3. run the commands on the sa_top RTL (Verilator, S = 8, always-ready memory,
     read latency 3; the harness of `make perf`);
  4. compare C with NumPy and the measured cycle counters with the prediction.
Nothing is written to results/. Usage: python3 scripts/demo/demo.py [--M --N --K]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "compiler")]

from sysarray import predict, tiler  # noqa: E402
from tb.common.runner import rtl, run  # noqa: E402
from tb.top.test_top import SOURCES  # noqa: E402

S, LATENCY = 8, 3
LOG = REPO / "build" / "demo" / "demo_sim.log"


@contextlib.contextmanager
def quiet(path: Path):
    """Send the simulator's output (fd 1 and 2, incl. Verilator and cocotb) to a log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    with open(path, "w") as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--M", type=int, default=128)
    ap.add_argument("--N", type=int, default=64)
    ap.add_argument("--K", type=int, default=768)
    a = ap.parse_args()
    m, n, k = a.M, a.N, a.K

    zeros = tiler.tile(np.zeros((m, k), dtype=np.int64), np.zeros((k, n), dtype=np.int64), s=S)
    pred = predict.predict(zeros.commands, s=S, read_latency=LATENCY,
                           useful_macs=zeros.stats.useful_macs)  # fmt: skip
    print(f"SysArray demo: C = A·B with A {m}×{k}, B {k}×{n} (int8 → int32), S = {S}")
    print(f"  compiled: {len(zeros.commands)} commands (LOAD_W / LOAD_A / COMPUTE / STORE)")
    print(f"  predicted (analytical, sysarray.predict): {pred.cycles_total:,} cycles, "
          f"utilization {pred.utilization:.4f}")  # fmt: skip
    print("  running on the RTL (Verilator) ...", flush=True)

    shape = [{"shape_id": "demo", "M": m, "N": n, "K": k, "order": "A", "m_c": None}]
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(SYSARRAY_PERF_SHAPES=json.dumps(shape), SYSARRAY_RESULTS_DIR=tmp)
        try:
            with quiet(LOG):
                run(toplevel="sa_top", sources=rtl(*SOURCES), test_module="tb.perf.cocotb_perf",
                    block_dir=REPO / "tb" / "perf", parameters={"S": S})  # fmt: skip
        except Exception as e:  # noqa: BLE001 - report and fail
            print(f"  simulation failed: {e} (log: {LOG.relative_to(REPO)})")
            print("  check the tools first: make check (Verilator must be >= 5.036)")
            return 1
        rec = json.loads((Path(tmp) / "perf.jsonl").read_text().splitlines()[0])
    wall = time.time() - t0
    util = rec["useful_macs"] / (S * S * rec["cycles_total"])
    same = rec["cycles_total"] == pred.cycles_total
    print(f"  measured (RTL cycle counter): {rec['cycles_total']:,} cycles, utilization {util:.4f}")
    print(f"  C matches NumPy: {'yes' if rec['c_ok'] else 'NO'}")
    print(f"  measured == predicted: {'yes' if same else 'NO'}")
    print(f"  wall clock {wall:.0f} s (the first run also builds the simulator); seed "
          f"{rec['seed']}; simulator log {LOG.relative_to(REPO)}")  # fmt: skip
    return 0 if (rec["c_ok"] and same) else 1


if __name__ == "__main__":
    sys.exit(main())
