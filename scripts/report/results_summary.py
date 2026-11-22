#!/usr/bin/env python3
"""Generate docs/RESULTS_SUMMARY.md from results/ (M14).

Every number in the summary is read from a file in results/ (produced by the
script named in that file or in docs/RESULTS.md); nothing is typed by hand.
scripts/report/test_results_summary.py fails if the committed summary differs
from a fresh generation, so it cannot drift.

Usage (repo root): python3 scripts/report/results_summary.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "RESULTS_SUMMARY.md"


def result_files(results: Path) -> list[Path]:
    """Summary files this report covers (raw/ dumps and tool inputs excluded)."""
    files = []
    for sub, pattern in (("verification", "campaign_*.json"), ("latency", "latency_*.csv"),
                         ("perf", "*.csv"), ("synth", "*.json"), ("asic", "*.json"),
                         ("scalesim", "**/COMPUTE_REPORT.csv")):  # fmt: skip
        files += sorted((results / sub).glob(pattern))
    return files


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO))


def _f(v: object, fmt: str) -> str:
    return "–" if v is None else format(v, fmt)


def _verification(results: Path) -> list[str]:
    rows = ["| File | GEMMs | Failures | Exact-timing checks | Wall clock |",
            "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted((results / "verification").glob("campaign_*.json")):
        d = json.loads(f.read_text())
        checks, wall = d.get("exact_timing_checks", "–"), d.get("wall_clock_s", "–")
        rows.append(f"| `{_rel(f)}` | {d['gemms']:,} | {d['failures']} | {checks} | {wall} s |")
    return rows


def _latency(results: Path) -> list[str]:
    rows = ["| File | Rows | Measured = model |", "| --- | --- | --- |"]
    for f in sorted((results / "latency").glob("latency_*.csv")):
        data = list(csv.DictReader(f.open()))
        ok = sum(r["match"] == "True" for r in data)
        rows.append(f"| `{_rel(f)}` | {len(data)} | {ok} / {len(data)} |")
    return rows


def _perf(results: Path) -> list[str]:
    out = []
    for f in sorted((results / "perf").glob("*.csv")):
        data = list(csv.DictReader(f.open()))
        eq = sum(r["cycles_total"] == r["predicted_cycles"] for r in data)
        cok = sum(r["c_ok"] == "True" for r in data)
        out += [f"`{_rel(f)}`: {len(data)} runs, measured = predicted in {eq}, "
                f"C correct in {cok}.",
                "", "| Shape | Order | m_c | Cycles | Predicted | Utilization |",
                "| --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for r in data:
            out.append(f"| {r['shape_id']} | {r['order']} | {r['m_c']} | "
                       f"{int(r['cycles_total']):,} | {int(r['predicted_cycles']):,} | "
                       f"{float(r['utilization']):.4f} |")  # fmt: skip
        out.append("")
    return out


def _synth(results: Path) -> list[str]:
    rows = ["| File | Top | S | Seed | Fmax (MHz) | LUT4 | FF | CCU2C | MULT18X18D | DP16KD |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted((results / "synth").glob("*.json")):
        d = json.loads(f.read_text())
        c = d["yosys_cells"]
        fmax = next(iter(d["fmax_mhz"].values()), None)
        rows.append(f"| `{_rel(f)}` | {d['top']} | {d['S']} | {d['nextpnr_seed']} | "
                    f"{_f(fmax, '.2f')} | {c.get('LUT4', 0):,} | {c.get('TRELLIS_FF', 0):,} | "
                    f"{c.get('CCU2C', 0):,} | {c.get('MULT18X18D', 0)} | "
                    f"{c.get('DP16KD', 0)} |")  # fmt: skip
    return rows


def _asic(results: Path) -> list[str]:
    rows = ["| File | S | Period (ns) | I/O % | Flow | WS setup (ns) | WS hold (ns) | "
            "Max-slew viol. | Core (mm²) | Std cells | Std-cell area (mm²) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted((results / "asic").glob("*.json")):
        d = json.loads(f.read_text())
        t, a = d["timing_ns"], d["area_um2"]
        flow = d.get("flow", {}).get("status", "ok")
        rows.append(f"| `{_rel(f)}` | {d['S']} | {d['clock_period_ns']:g} | "
                    f"{d['io_delay_constraint_pct']} | {flow} | "
                    f"{_f(t['setup_ws_worst_corner'], '+.3f')} | "
                    f"{_f(t['hold_ws_worst_corner'], '+.3f')} | "
                    f"{_f(d['signoff'].get('max_slew_violations'), ',')} | {a['core'] / 1e6:.3f} | "
                    f"{d['cells']['stdcell']:,} | {a['stdcell'] / 1e6:.3f} |")  # fmt: skip
    return rows


def _scalesim(results: Path) -> list[str]:
    rows = ["| File | Layer | Total cycles (incl. prefetch) | Stall cycles | Overall util. % |",
            "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted((results / "scalesim").glob("**/COMPUTE_REPORT.csv")):
        for r in csv.reader(f.open()):
            if not r or not r[0].strip().isdigit():
                continue
            rows.append(f"| `{_rel(f)}` | {r[0].strip()} | {int(r[1]):,} | {int(r[3]):,} | "
                        f"{float(r[4]):.1f} |")  # fmt: skip
    return rows


def render(results: Path) -> str:
    parts = [
        "# Results summary (generated)",
        "",
        "Generated by `scripts/report/results_summary.py` from `results/`; do not edit by",
        "hand. The producing commit and script of every file are in `docs/RESULTS.md`.",
        "Layer IDs in the SCALE-Sim table follow the topology file next to each report.",
        "",
        "## Verification campaigns (random compiler-driven GEMMs, `make campaign`)", "",
        *_verification(results), "",
        "## Array latency (measured vs model)", "", *_latency(results), "",
        "## Performance (`make perf`, S = 8)", "", *_perf(results),
        "## FPGA synthesis (ECP5 LFE5U-85F, speed 6)", "", *_synth(results), "",
        "## ASIC (SKY130, LibreLane)", "", *_asic(results), "",
        "## SCALE-Sim", "", *_scalesim(results), "",
    ]  # fmt: skip
    return "\n".join(parts)


def main() -> int:
    OUT.write_text(render(REPO / "results"))
    print(f"results_summary: wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
