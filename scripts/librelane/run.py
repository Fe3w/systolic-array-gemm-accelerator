#!/usr/bin/env python3
"""LibreLane (SKY130) run of `sa_array` for one S and clock period (M12).

Runs the LibreLane Docker image prepared by scripts/librelane/setup.sh on the
committed RTL, then writes

  results/asic/sa_array_S<S>_<sha>_<period>ns.json   summary (this script's fields)
  results/asic/raw/<name>/metrics.json.gz            LibreLane's full final metrics
  results/asic/raw/<name>/sta_summary.rpt            post-route STA, all corners
  results/asic/raw/<name>/resolved.json.gz           the full resolved flow config

The full run directory stays in build/asic/<name>/ (GDS, DEF, logs; not committed).

Timing: LibreLane signs off at nine corners (nom/min/max wire RC x tt/ss/ff).
`setup_ws_worst_corner` is the worst setup slack over all of them (the slow
ss_100C_1v60 corners); `nom_tt_025C_1v80` is the typical corner. LibreLane's
default I/O constraint is 20 % of the period on every port (--io-delay changes it). `fmax_mhz` =
1000 / (period - worst setup slack) per corner: the clock at which that slack
would be zero, assuming the paths and I/O budget scale with the period.

Usage (repo root): python3 scripts/librelane/run.py --S 8 --period 20
Env: LIBRELANE_IMAGE, PDK_ROOT (as in setup.sh).
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("LIBRELANE_IMAGE", "ghcr.io/librelane/librelane:3.0.17")
PDK_ROOT = Path(os.environ.get("PDK_ROOT", Path.home() / ".sysarray-pdk"))
PDK = "sky130A"
PDK_VERSION = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
SOURCES = ["rtl/common/sa_reg.sv", "rtl/pe/sa_pe.sv", "rtl/array/sa_grid.sv",
           "rtl/array/sa_array.sv"]  # fmt: skip
TYP = "nom_tt_025C_1v80"


def _num(v: object) -> float | int | None:
    """JSON-safe number: LibreLane writes Infinity when a path class is empty."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        return v
    return None


def _fmax(period: float, ws: float | None) -> float | None:
    if ws is None or period - ws <= 0:
        return None
    return round(1000.0 / (period - ws), 2)


def summarize(m: dict, period_ns: float) -> dict:
    """The fields this project reports, from LibreLane's final/metrics.json."""
    g = lambda k: _num(m.get(k))  # noqa: E731
    corners = sorted({k.split("corner:")[1] for k in m if "__corner:" in k})
    setup_by = {c: g(f"timing__setup__ws__corner:{c}") for c in corners}
    hold_by = {c: g(f"timing__hold__ws__corner:{c}") for c in corners}
    ws = g("timing__setup__ws")
    return {
        "area_um2": {"die": g("design__die__area"), "core": g("design__core__area"),
                     "stdcell": g("design__instance__area__stdcell")},  # fmt: skip
        "cells": {
            "stdcell": g("design__instance__count__stdcell"),
            "sequential": g("design__instance__count__class:sequential_cell"),
            "combinational": g("design__instance__count__class:multi_input_combinational_cell"),
        },
        "utilization": g("design__instance__utilization__stdcell"),
        "timing_ns": {
            "setup_ws_worst_corner": ws,
            "setup_tns_worst_corner": g("timing__setup__tns"),
            "setup_r2r_ws_worst_corner": g("timing__setup_r2r__ws"),
            "hold_ws_worst_corner": g("timing__hold__ws"),
            "hold_tns_worst_corner": g("timing__hold__tns"),
            "setup_ws_by_corner": setup_by,
            "hold_ws_by_corner": hold_by,
        },
        "fmax_mhz": {"worst_corner": _fmax(period_ns, ws),
                     **{TYP: _fmax(period_ns, setup_by.get(TYP))}},  # fmt: skip
        "signoff": {
            "magic_drc_errors": g("magic__drc_error__count"),
            "klayout_drc_errors": g("klayout__drc_error__count"),
            "route_drc_errors": g("route__drc_errors"),
            "lvs_errors": g("design__lvs_error__count"),
            "antenna_violations": g("route__antenna_violation__count"),
            "max_slew_violations": g("design__max_slew_violation__count"),
            "flow_errors": g("flow__errors__count"),
        },
        "power_w_total": g("power__total"),
    }


def parse_overrides(items: list[str]) -> dict:
    """--set KEY=VALUE pairs; VALUE is parsed as JSON when it can be (true, 30, [..])."""
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key or not key.replace("_", "").isalnum():
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def flow_error(log_text: str) -> str | None:
    """LibreLane's final error message ("The following error was encountered ..."), joined."""
    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        if "The following error was encountered" in line:
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("[") or "will now quit" in nxt:
                    break
                body.append(nxt.split("  ")[0].strip() if "__main__.py" in nxt else nxt.strip())
            text = " ".join(t for t in body if t)
            return text.removeprefix("running the flow:").strip() or None
    return None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def git_commit() -> str:
    dirty = git("status", "--porcelain", "--", "rtl", "scripts/librelane")
    return git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else "")


def tool_versions() -> dict:
    cmd = ("echo librelane=$(python3 -c 'import librelane; print(librelane.__version__)'); "
           "echo openroad=$(openroad -version 2>&1 | tail -1); "
           "echo yosys=$(yosys -V 2>&1 | tail -1 | cut -c1-40); "
           "echo magic=$(magic --version 2>&1 | tail -1); "
           "echo netgen=$(netgen -batch quit 2>&1 | grep -m1 -i netgen | cut -c1-40)")  # fmt: skip
    out = subprocess.run(["docker", "run", "--rm", IMAGE, "bash", "-lc", cmd],
                         capture_output=True, text=True).stdout  # fmt: skip
    vers = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"image": IMAGE, **vers}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--S", type=int, default=8)
    ap.add_argument("--period", type=float, required=True, help="clock period in ns")
    ap.add_argument("--core-util", type=int, default=40, help="FP_CORE_UTIL in percent")
    ap.add_argument("--hold-margin", type=float, default=None,
                    help="PL_/GRT_RESIZER_HOLD_SLACK_MARGIN in ns (LibreLane default if unset)")
    ap.add_argument("--io-delay", type=int, default=None,
                    help="IO_DELAY_CONSTRAINT in percent of the period (LibreLane default 20)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="extra LibreLane config value (repeatable; JSON values allowed)")
    ap.add_argument("--tag", default=None, help="name suffix for runs that use --set")
    ap.add_argument("--resummarize", action="store_true",
                    help="only (re)write the summary of the existing build/asic run with these "
                         "options; --commit names the commit that run was made at")  # fmt: skip
    ap.add_argument("--commit", help="with --resummarize: the run's commit (default HEAD)")
    args = ap.parse_args()

    if args.set and not args.tag:
        ap.error("--set needs --tag, so runs with different settings get different names")
    commit = args.commit if (args.resummarize and args.commit) else git_commit()
    ptag = f"{args.period:g}".replace(".", "p")
    name = f"sa_array_S{args.S}_{commit}_{ptag}ns"
    if args.hold_margin is not None:
        name += f"_hold{args.hold_margin:g}".replace(".", "p")
    if args.io_delay is not None:
        name += f"_io{args.io_delay}"
    if args.tag:
        name += f"_{args.tag}"
    work = REPO / "build" / "asic" / name
    if args.resummarize:
        log_text = (work / "librelane.log").read_text()
        rc = 2 if "will now quit" in log_text else 0
        return write_results(args, name, commit, work, rc, None, log_text)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    config = {
        "DESIGN_NAME": "sa_array",
        "VERILOG_FILES": [f"/repo/{s}" for s in SOURCES],
        "SYNTH_PARAMETERS": [f"S={args.S}"],
        "CLOCK_PORT": "clk",
        "CLOCK_PERIOD": args.period,
        "FP_CORE_UTIL": args.core_util,
    }
    if args.hold_margin is not None:
        config["PL_RESIZER_HOLD_SLACK_MARGIN"] = args.hold_margin
        config["GRT_RESIZER_HOLD_SLACK_MARGIN"] = args.hold_margin
    if args.io_delay is not None:
        config["IO_DELAY_CONSTRAINT"] = args.io_delay
    config.update(parse_overrides(args.set))
    (work / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    t0 = time.time()
    cmd = ["docker", "run", "--rm", "-v", f"{REPO}:/repo", "-v", f"{PDK_ROOT.resolve()}:/pdk",
           "-w", f"/repo/build/asic/{name}", IMAGE, "librelane", "--pdk-root", "/pdk",
           "--manual-pdk", "--pdk", PDK, "--run-tag", "run", "config.json"]  # fmt: skip
    with open(work / "librelane.log", "w") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    wall = round(time.time() - t0)
    run_dir = work / "runs" / "run"
    metrics_file = run_dir / "final" / "metrics.json"
    log_text = (work / "librelane.log").read_text()
    if not metrics_file.exists():
        tail = "\n".join(log_text.splitlines()[-30:])
        print(f"librelane failed (rc={rc}, {wall} s), no metrics; log in {work}\n{tail}")
        return 1
    return write_results(args, name, commit, work, rc, wall, log_text)


def write_results(args: argparse.Namespace, name: str, commit: str, work: Path, rc: int,
                  wall: int | None, log_text: str) -> int:
    """Summary + raw files for a run that produced final metrics. A run can finish
    place-and-route and still fail sign-off (rc != 0): it is recorded with its error,
    so failed runs are as visible as passing ones. wall = None: not measured
    (--resummarize)."""
    run_dir = work / "runs" / "run"
    metrics_file = run_dir / "final" / "metrics.json"
    metrics = json.loads(metrics_file.read_text())
    raw = REPO / "results" / "asic" / "raw" / name
    raw.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw / "metrics.json.gz", "wt") as f:
        f.write(metrics_file.read_text())
    with gzip.open(raw / "resolved.json.gz", "wt") as f:
        f.write((run_dir / "resolved.json").read_text())
    sta = sorted(run_dir.glob("*-openroad-stapostpnr/summary.rpt"))
    if sta:
        shutil.copy(sta[-1], raw / "sta_summary.rpt")

    summary = {
        "top": "sa_array",
        "S": args.S,
        "git_commit": commit,
        "pdk": {"name": PDK, "version": PDK_VERSION},
        "clock_period_ns": args.period,
        "fp_core_util_pct": args.core_util,
        "io_delay_constraint_pct": 20 if args.io_delay is None else args.io_delay,
        "hold_slack_margin_ns": args.hold_margin,
        "config_overrides": parse_overrides(args.set),
        "flow": {"rc": rc, "status": "ok" if rc == 0 else "failed",
                 "error": flow_error(log_text) if rc != 0 else None},
        **summarize(metrics, args.period),
        "wall_clock_s": wall,
        "tools": tool_versions(),
        "script": "scripts/librelane/run.py",
    }
    out = REPO / "results" / "asic" / f"{name}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"asic: wrote {out.relative_to(REPO)} ({wall} s, flow {summary['flow']['status']})")
    show = ("area_um2", "cells", "timing_ns", "fmax_mhz", "signoff")
    print(json.dumps({k: summary[k] for k in show}, indent=1))
    return 0 if rc == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
