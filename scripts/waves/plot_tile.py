#!/usr/bin/env python3
"""Waveform figure of one sa_array tile (load, compute, drain) from a VCD (M11, BRIEF §12).

Produce the VCD (S = 4, seed 5):
    SYSARRAY_WAVES=1 SYSARRAY_SEED=5 python3 -m pytest "tb/array/test_array.py::test_sa_array[4]"
Then:
    python3 scripts/waves/plot_tile.py tb/array/sim_build/<dir>/dump.vcd docs/img/tile_s4.png
The window starts 1 cycle before the first w_load in the VCD (test_directed's
first tile: identity weights, 3 rows) and spans `--cycles` cycles. Signals are
sampled once per cycle after the falling-edge drive (scripts/waves/vcd_cycle_table.py).
"""

from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
HIGH = "#2a78d6"  # categorical slot 1
SIGNALS = ["w_load", "a_valid", "grid_a_valid", "grid_valid", "c_valid"]


def read_samples(path: str) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Per-cycle samples and declared widths (VCD drops leading zeros of vectors)."""
    ids, widths, scope, cur, samples, pending = {}, {}, [], {}, [], False
    for line in open(path):
        s = line.strip()
        if s.startswith("$scope"):
            scope.append(s.split()[2])
        elif s.startswith("$upscope"):
            scope.pop()
        elif s.startswith("$var"):
            p = s.split()
            if scope == ["sa_array"] and p[4] in SIGNALS + ["clk"]:
                ids[p[3]] = p[4]
                widths[p[4]] = int(p[2])
        elif s.startswith("#"):
            if pending:
                samples.append(dict(cur))
                pending = False
        elif s and s[0] in "01xz" and s[1:] in ids:
            name = ids[s[1:]]
            if name == "clk" and cur.get("clk") == "1" and s[0] == "0":
                pending = True
            cur[name] = s[0]
        elif s.startswith("b"):
            v, code = s[1:].split()
            if code in ids:
                cur[ids[code]] = v
    return samples, widths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vcd")
    ap.add_argument("out")
    ap.add_argument("--cycles", type=int, default=20)
    args = ap.parse_args()
    samples, widths = read_samples(args.vcd)
    start = next(i for i, x in enumerate(samples) if x.get("w_load") == "1") - 1
    win = samples[start : start + args.cycles]
    s = widths["grid_valid"]
    rows = [("w_load", None), ("a_valid", None)]
    rows += [(f"row {r} valid (after skew)", ("grid_a_valid", r)) for r in range(s)]
    rows += [(f"col {c} valid (grid out)", ("grid_valid", c)) for c in range(s)]
    rows += [("c_valid (after de-skew)", None)]

    def bit(x: dict, key) -> int:
        if key is None:
            return 0
        name, i = key
        v = x[name].zfill(s)
        return int(v[len(v) - 1 - i] == "1")

    fig, ax = plt.subplots(figsize=(10, 0.42 * len(rows) + 1.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for k, (label, key) in enumerate(rows):
        y0 = len(rows) - 1 - k
        name = label.split(" ")[0] if key is None else None
        vals = [int(x[name] == "1") if name else bit(x, key) for x in win]
        if label.startswith("c_valid"):
            vals = [int(x["c_valid"] == "1") for x in win]
        for t, v in enumerate(vals):
            if v:
                ax.add_patch(plt.Rectangle((t, y0 + 0.15), 1, 0.6, color=HIGH, linewidth=0))
        xs = [t for t in range(len(vals) + 1) for _ in (0, 1)][1:-1]
        ys = [y0 + 0.15 + 0.6 * vals[t] for t in range(len(vals)) for _ in (0, 1)]
        ax.plot(xs, ys, color=INK2, linewidth=1)
        ax.text(-0.3, y0 + 0.45, label, ha="right", va="center", fontsize=8, color=INK)
    for t in range(len(win) + 1):
        ax.axvline(t, color=GRID, linewidth=0.5, zorder=0)
    ax.set_xlim(0, len(win))
    ax.set_ylim(-0.2, len(rows))
    ax.set_yticks([])
    ax.set_xticks([t + 0.5 for t in range(len(win))], [str(t) for t in range(len(win))])
    ax.tick_params(colors=INK2, labelsize=7, length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("cycle (0 = one cycle before the first w_load)", color=INK2, fontsize=8)
    ax.set_title(f"sa_array S = {s}: one tile — weight load, input skew, fill, de-skew, drain",
                 color=INK, fontsize=10, loc="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"waves: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
