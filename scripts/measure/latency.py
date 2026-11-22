#!/usr/bin/env python3
"""Measure sa_array latency and per-tile cycles (M4) and write results/latency/latency_<sha>.csv.

Runs tb/array/cocotb_latency.py on Verilator for each S, merges the per-S
fragments, adds the analytical predictions of docs/spec/array.md §4

    predicted_latency = 2S            (two-stage MAC since M7b; 2S - 1 before)
    predicted_t_tile  = M + 3S        (S load cycles + M rows + 2S latency)

and a `match` column. Exits non-zero if any simulation test fails or any row
does not match. Usage (from the repo root): python3 scripts/measure/latency.py
Environment: SYSARRAY_SEED (optional) as for every test; the seed is recorded.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "compiler")]

from cocotb_tools.check_results import get_results  # noqa: E402

from tb.common.runner import build_dir_for, rtl, run  # noqa: E402

SIZES = (4, 8)
SOURCES = ("common/sa_reg.sv", "pe/sa_pe.sv", "array/sa_grid.sv", "array/sa_array.sv")
COLUMNS = [
    "S",
    "M",
    "latency_first",
    "t_tile",
    "predicted_latency",
    "predicted_t_tile",
    "match",
    "seed",
    "git_commit",
]


def git_commit() -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "rtl", "tb", "scripts"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def main() -> int:
    commit = git_commit()
    block_dir = REPO / "tb" / "array"
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SYSARRAY_RESULTS_DIR"] = tmp
        for s in SIZES:
            params = {"S": s, "DATA_W": 8, "ACC_W": 32}
            run(
                toplevel="sa_array",
                sources=rtl(*SOURCES),
                test_module="tb.array.cocotb_latency",
                block_dir=block_dir,
                parameters=params,
            )
            n_tests, n_failed = get_results(
                build_dir_for(block_dir, "sa_array", params) / "results.xml"
            )
            if n_tests == 0 or n_failed:
                print(f"latency: S={s}: {n_failed} of {n_tests} simulation tests failed")
                return 1
            with open(Path(tmp) / f"latency_S{s}.csv", newline="") as f:
                for r in csv.DictReader(f):
                    s_, m = int(r["S"]), int(r["M"])
                    pred_lat, pred_t = 2 * s_, m + 3 * s_
                    lat, t_tile = int(r["latency_first"]), int(r["t_tile"])
                    rows.append(
                        {
                            "S": s_,
                            "M": m,
                            "latency_first": lat,
                            "t_tile": t_tile,
                            "predicted_latency": pred_lat,
                            "predicted_t_tile": pred_t,
                            "match": lat == pred_lat and t_tile == pred_t,
                            "seed": r["seed"],
                            "git_commit": commit,
                        }
                    )

    out = REPO / "results" / "latency" / f"latency_{commit}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"latency: wrote {out.relative_to(REPO)} ({len(rows)} rows)")
    for r in rows:
        print("  " + ", ".join(f"{k}={r[k]}" for k in COLUMNS[:7]))
    bad = [r for r in rows if not r["match"]]
    if bad:
        print(f"latency: {len(bad)} row(s) differ from the model")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
