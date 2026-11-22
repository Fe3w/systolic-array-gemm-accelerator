#!/usr/bin/env python3
"""Benchmark the BRIEF §9.2 shapes on the RTL (M11) -> results/perf/<run_id>.csv.

Runs tb/perf/cocotb_perf.py on sa_top (S = 8, always-ready memory, L = 3) for
every shape at the tiler default m_c (min(M, 128) since M13, ping-pong halves; order A),
plus an order comparison A vs B at m_c = 64 for a few shapes. Columns follow
BRIEF §9.3 (+ m_c, traffic bytes, C check). utilization = useful_macs /
(S^2 * cycles_total); predicted_* from sysarray.predict (predicted, analytical).
Usage (repo root): python3 scripts/measure/perf.py [--quick]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "compiler")]

from cocotb_tools.check_results import get_results  # noqa: E402

from tb.common.runner import build_dir_for, rtl, run  # noqa: E402
from tb.top.test_top import SOURCES  # noqa: E402

S = 8
SHAPES = {  # BRIEF §9.2
    "sq8": (8, 8, 8),
    "sq16": (16, 16, 16),
    "sq64": (64, 64, 64),
    "sq256": (256, 256, 256),
    "bert_proj": (128, 768, 768),
    "bert_ffn_down": (128, 768, 3072),
    "bert_ffn_up": (128, 3072, 768),
    "r50_3x3": (3136, 64, 576),
    "r50_1x1": (3136, 256, 64),
    "odd": (100, 37, 53),
}
ORDER_COMPARE = ("sq256", "bert_proj", "r50_1x1")
COLUMNS = ["shape_id", "M", "N", "K", "S", "order", "m_c", "bw_dma", "cycles_total",
           "cycles_compute", "cycles_dma", "useful_macs", "macs_issued", "utilization",
           "predicted_cycles", "predicted_utilization", "weight_bytes", "act_bytes",
           "out_bytes", "c_ok", "git_commit", "seed"]  # fmt: skip


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="small shapes only (smoke test)")
    args = ap.parse_args()
    dirty = git("status", "--porcelain", "--", "rtl", "tb", "compiler", "scripts")
    commit = git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else "")
    names = ["sq8", "sq16", "odd"] if args.quick else list(SHAPES)
    runs = [{"shape_id": n, "M": SHAPES[n][0], "N": SHAPES[n][1], "K": SHAPES[n][2],
             "order": "A", "m_c": None} for n in names]  # fmt: skip
    if not args.quick:
        for n in ORDER_COMPARE:
            for order in ("A", "B"):
                runs.append({"shape_id": n, "M": SHAPES[n][0], "N": SHAPES[n][1],
                             "K": SHAPES[n][2], "order": order, "m_c": 64})  # fmt: skip
    block, params = REPO / "tb" / "perf", {"S": S}
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(SYSARRAY_PERF_SHAPES=json.dumps(runs), SYSARRAY_RESULTS_DIR=tmp)
        run(toplevel="sa_top", sources=rtl(*SOURCES), test_module="tb.perf.cocotb_perf",
            block_dir=block, parameters=params)  # fmt: skip
        n_tests, n_failed = get_results(build_dir_for(block, "sa_top", params) / "results.xml")
        recs = [json.loads(x) for x in (Path(tmp) / "perf.jsonl").read_text().splitlines()]
    rows = []
    for r in recs:
        util = r["useful_macs"] / (S * S * r["cycles_total"])
        putil = r["useful_macs"] / (S * S * r["predicted_cycles"])
        row = {c: r.get(c) for c in COLUMNS if c in r}
        row.update(bw_dma="1 row/cycle (L=3)", utilization=round(util, 4),
                   predicted_utilization=round(putil, 4), git_commit=commit)  # fmt: skip
        rows.append(row)
    run_id = commit + ("_quick" if args.quick else "")
    out = REPO / "results" / "perf" / f"{run_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"perf: wrote {out.relative_to(REPO)} ({len(rows)} rows, {time.time() - t0:.0f} s)")
    for r in rows:
        print(f"  {r['shape_id']:14s} {r['order']} m_c={r['m_c']:3d} cycles={r['cycles_total']:9d}"
              f" pred={r['predicted_cycles']:9d} util={r['utilization']:.3f}")  # fmt: skip
    ok = n_tests and not n_failed and all(r["c_ok"] for r in rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
