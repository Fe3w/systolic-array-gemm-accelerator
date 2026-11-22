#!/usr/bin/env python3
"""Plots for M11 from a results/perf/<run_id>.csv (written by scripts/measure/perf.py).

Writes next to the CSV:
  <run_id>_utilization.png  measured utilization per shape (order A, m_c = min(M, 256)),
                            predicted value as a tick; plus order A vs B at m_c = 64
  <run_id>_roofline.png     measured MACs/cycle vs arithmetic intensity (MACs per DMA byte)
                            under the S^2 peak and the 1-row/cycle DMA roof
Usage: python3 scripts/measure/plot_perf.py results/perf/<run_id>.csv
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834"]  # categorical slots 1-2 (validated adjacent pair)


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def main(path: str) -> int:
    csv_path = Path(path)
    rows = list(csv.DictReader(open(csv_path)))
    s = int(rows[0]["S"])
    base = [r for r in rows if r["order"] == "A" and int(r["m_c"]) == min(int(r["M"]), 256)]
    both = {r["shape_id"] for r in rows if r["order"] == "B"}  # shapes run in both orders
    comp = [r for r in rows if int(r["m_c"]) == 64 and r["shape_id"] in both]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [3, 1.3]}, facecolor=SURFACE
    )
    names = [r["shape_id"] for r in base]
    util = [float(r["utilization"]) for r in base]
    pred = [float(r["predicted_utilization"]) for r in base]
    x = range(len(base))
    _style(ax1)
    ax1.bar(x, util, width=0.6, color=SERIES[0], label="measured (RTL counters)")
    ax1.scatter(x, pred, marker="_", s=500, color=INK, linewidths=2, zorder=3,
                label="predicted (analytical)")  # fmt: skip
    for i, u in enumerate(util):
        ax1.annotate(f"{u:.2f}", (i, u), textcoords="offset points", xytext=(0, 6),
                     ha="center", fontsize=8, color=INK2)  # fmt: skip
    ax1.set_xticks(list(x), names, rotation=30, ha="right")
    ax1.set_ylabel("utilization = useful MACs / (S² · cycles)", color=INK2, fontsize=9)
    ax1.set_ylim(0, max(util) * 1.25)
    ax1.set_title(f"SysArray S = {s}: utilization per GEMM shape (order A)", color=INK,
                  fontsize=11, loc="left")  # fmt: skip
    ax1.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")

    _style(ax2)
    shapes = sorted({r["shape_id"] for r in comp}, key=[r["shape_id"] for r in comp].index)
    w = 0.38
    for j, order in enumerate(("A", "B")):
        vals = [next(float(r["utilization"]) for r in comp
                     if r["shape_id"] == sh and r["order"] == order) for sh in shapes]  # fmt: skip
        xs = [i + (j - 0.5) * (w + 0.03) for i in range(len(shapes))]
        ax2.bar(xs, vals, width=w, color=SERIES[j], label=f"order {order}")
        for xi, v in zip(xs, vals, strict=True):
            ax2.annotate(f"{v:.2f}", (xi, v), textcoords="offset points", xytext=(0, 4),
                         ha="center", fontsize=7, color=INK2)  # fmt: skip
    ax2.set_xticks(range(len(shapes)), shapes, rotation=30, ha="right")
    ax2.set_ylim(0, ax1.get_ylim()[1])
    ax2.set_title("tile order, m_c = 64", color=INK, fontsize=11, loc="left")
    ax2.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    out1 = csv_path.with_name(csv_path.stem + "_utilization.png")
    fig.savefig(out1, dpi=150, facecolor=SURFACE)

    fig, ax = plt.subplots(figsize=(7, 4.8), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="both", color=GRID, linewidth=0.8)
    peak, bw = s * s, s  # MACs/cycle; DMA bytes/cycle (one S-byte row per cycle)
    xi = [i / 4 for i in range(1, 4 * 64)]
    ax.plot(xi, [min(peak, i * bw) for i in xi], color=INK2, linewidth=2,
            label=f"roof: min({peak}, {bw} B/cycle × intensity)")  # fmt: skip
    placed: list[tuple[float, float, list[str]]] = []  # log10 position, shape names
    for idx, r in enumerate(
        sorted(base, key=lambda r: int(r["useful_macs"]) / int(r["cycles_total"]))
    ):
        traffic = int(r["weight_bytes"]) + int(r["act_bytes"]) + int(r["out_bytes"])
        inten = int(r["useful_macs"]) / traffic
        perf = int(r["useful_macs"]) / int(r["cycles_total"])
        ax.scatter([inten], [perf], s=40, color=SERIES[0], edgecolors=SURFACE, linewidths=2,
                   zorder=3)  # fmt: skip
        lx, ly = math.log10(inten), math.log10(perf)
        near = [i for i, (px, py, _) in enumerate(placed) if abs(lx - px) < 0.03 and abs(ly - py) < 0.03]
        if near:  # points on top of each other share one label, written below them
            px, py, names = placed[near[0]]
            placed[near[0]] = (px, py, names + [r["shape_id"]])
            continue
        placed.append((lx, ly, [r["shape_id"]]))
    for idx, (lx, ly, names) in enumerate(placed):
        dy = (-11 if idx % 2 == 0 else 6) if len(names) == 1 else -12 - 9 * (len(names) - 1)
        ax.annotate("\n".join(names), (10 ** lx, 10 ** ly), textcoords="offset points",
                    xytext=(6, dy), fontsize=7, color=INK2)  # fmt: skip
    ax.set_xscale("log")
    ax.set_yscale("log")
    plain = FuncFormatter(lambda v, _: f"{v:g}")
    ax.xaxis.set_major_formatter(plain)
    ax.yaxis.set_major_formatter(plain)
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.set_yticks([2, 4, 8, 16, 32, peak])
    ax.set_xlabel("arithmetic intensity (useful MACs per DMA byte)", color=INK2, fontsize=9)
    ax.set_ylabel("useful MACs per cycle (measured)", color=INK2, fontsize=9)
    ax.set_title(f"SysArray S = {s}: roofline ({csv_path.name})", color=INK,
                 fontsize=11, loc="left")  # fmt: skip
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower right")
    fig.tight_layout()
    out2 = csv_path.with_name(csv_path.stem + "_roofline.png")
    fig.savefig(out2, dpi=150, facecolor=SURFACE)
    print(f"plot: wrote {out1} and {out2}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
