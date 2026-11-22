#!/usr/bin/env python3
"""Run the long verification campaign (M10) and write results/verification/campaign_<sha>.json.

Runs tb/campaign/cocotb_campaign.py on sa_top at S = 8 with
SYSARRAY_CAMPAIGN_N GEMMs (default 1000) and SYSARRAY_LONG=1 (adds the
int32-wrap corner), collects one JSON record per GEMM, and summarizes: count,
failures, seed, shape/order/memory-setting histograms, exact-timing checks,
wall-clock time. Exits non-zero on any failure.
Usage (repo root): python3 scripts/verify/campaign.py [--n 1000] [--S 8]
"""

from __future__ import annotations

import argparse
import collections
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


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def git_commit() -> str:
    dirty = git("status", "--porcelain", "--", "rtl", "tb", "compiler", "scripts")
    return git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else "")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--S", type=int, default=8)
    args = ap.parse_args()
    commit = git_commit()
    block = REPO / "tb" / "campaign"
    params = {"S": args.S}
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(SYSARRAY_CAMPAIGN_N=str(args.n), SYSARRAY_LONG="1",
                          SYSARRAY_RESULTS_DIR=tmp)  # fmt: skip
        run(toplevel="sa_top", sources=rtl(*SOURCES), test_module="tb.campaign.cocotb_campaign",
            block_dir=block, parameters=params)  # fmt: skip
        n_tests, n_failed = get_results(build_dir_for(block, "sa_top", params) / "results.xml")
        recs = read_jsonl(Path(tmp) / f"campaign_S{args.S}.jsonl")
        corners = read_jsonl(Path(tmp) / f"corners_S{args.S}.jsonl")
    wall = time.time() - t0

    def ok(r: dict) -> bool:
        return r["c_ok"] and r["timing_ok"] and r["err"] == 0

    hist = collections.Counter
    summary = {
        "script": "scripts/verify/campaign.py",
        "git_commit": commit,
        "S": args.S,
        "seed": recs[0]["seed"] if recs else None,
        "gemms": len(recs),
        "failures": sum(not ok(r) for r in recs),
        "cocotb_tests": n_tests,
        "cocotb_failures": n_failed,
        "exact_timing_checks": sum(r["timing_exact_check"] for r in recs),
        "orders": dict(hist(r["order"] for r in recs)),
        "stalls": {str(k): v for k, v in hist(r["stalls"] for r in recs).items()},
        "latency": {str(k): v for k, v in hist(r["latency"] for r in recs).items()},
        "max_outstanding": {str(k): v for k, v in hist(r["max_outstanding"] for r in recs).items()},
        "non_multiple_of_S_shapes": sum(
            any(d % args.S for d in (r["M"], r["N"], r["K"])) for r in recs
        ),
        "dims_max": {d: max(r[d] for r in recs) for d in ("M", "N", "K")},
        "corners": {r["corner"]: ok(r) for r in corners},
        "total_useful_macs": sum(r["useful_macs"] for r in recs),
        "wall_clock_s": round(wall, 1),
    }
    out = REPO / "results" / "verification" / f"campaign_{commit}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"campaign: wrote {out.relative_to(REPO)}")
    failed = summary["failures"] or n_failed or not all(summary["corners"].values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
