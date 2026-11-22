#!/usr/bin/env python3
"""README figures (portfolio README rework).

  docs/img/architecture.png            clean block picture of the accelerator
  docs/img/flow.png                     how a GEMM goes through the stack: tiling
                                        compiler -> command stream -> RTL, with the
                                        two checks (NumPy, performance model)
  docs/img/utilization_before_after.png PE utilization per GEMM shape, MVP vs
                                        double buffering, read from results/perf/

Every number in the second figure is read from the two perf CSVs (measured RTL
counters); nothing is typed in by hand. For each shape the first order-A row of
each file is used, the same rows as the README table.
Usage (repo root):
    python3 scripts/report/readme_figures.py [--out docs/img]
        [--mvp results/perf/f5c0a0c.csv] [--final results/perf/be6f466.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
INK, MUTED, ACCENT, FILL, FILL2 = "#1f2933", "#52606d", "#0b6e8a", "#e3f0f4", "#f5f7fa"
MVP_C, FINAL_C = "#9aa5b1", "#0b6e8a"
# Shapes shown, in this order (the large, realistic ones plus one odd shape).
SHAPES = ["sq256", "bert_proj", "bert_ffn_down", "bert_ffn_up", "r50_3x3", "r50_1x1", "odd"]


def _box(ax, x, y, w, h, title, sub="", fill=FILL):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fill, ec=INK, lw=1.2))  # fmt: skip
    if sub:
        ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=11,
                color=INK, weight="bold")  # fmt: skip
        ax.text(x + w / 2, y + h * 0.30, sub, ha="center", va="center", fontsize=8.6,
                color=MUTED, linespacing=1.35)  # fmt: skip
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=11,
                color=INK, weight="bold")  # fmt: skip


def _arrow(ax, x0, y0, x1, y1, text="", color=INK, dy=0.13):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=13,
                                 lw=1.3, color=color))  # fmt: skip
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + dy, text, ha="center", va="bottom",
                fontsize=8.5, color=color)  # fmt: skip


def flow(out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12.9, 4.4))
    ax.set_xlim(0, 12.9)
    ax.set_ylim(-0.1, 4.3)
    ax.axis("off")
    h, top, bot = 1.15, 2.85, 0.6
    gemm, comp, rtl, res = (0.2, 2.1), (3.0, 2.4), (6.6, 3.3), (10.7, 2.0)
    _box(ax, *gemm[:1], top, gemm[1], h, "GEMM", "C = A · B\nM × N × K, int8", fill=FILL2)
    _box(ax, comp[0], top, comp[1], h, "Tiling compiler",
         "Python: tiles, tile order,\npadding, buffer halves")  # fmt: skip
    _box(ax, rtl[0], top, rtl[1], h, "SysArray RTL",
         "SystemVerilog: 8 × 8 weight-stationary\narray, DMA, buffers, controller")  # fmt: skip
    _box(ax, res[0], top, res[1], h, "Result", "C (int32) and\ncycle counters", fill=FILL2)
    mid = top + h / 2
    _arrow(ax, gemm[0] + gemm[1], mid, comp[0], mid, "shape")
    _arrow(ax, comp[0] + comp[1], mid, rtl[0], mid, "commands", color=ACCENT)
    ax.text((comp[0] + comp[1] + rtl[0]) / 2, mid - 0.12, "LOAD_W\nLOAD_A\nCOMPUTE\nSTORE",
            fontsize=7.4, color=ACCENT, ha="center", va="top", linespacing=1.25)  # fmt: skip
    _arrow(ax, rtl[0] + rtl[1], mid, res[0], mid)

    chk = (10.2, 2.5)
    _box(ax, gemm[0], bot, gemm[1], h, "Golden model", "NumPy, int32 wrap", fill=FILL2)
    _box(ax, comp[0], bot, comp[1], h, "Performance model",
         "predicts cycles from\nthe command stream", fill=FILL2)  # fmt: skip
    _box(ax, chk[0], bot, chk[1], h, "Checks",
         "C bit-exact vs NumPy\nmeasured = predicted cycles")  # fmt: skip
    for x, w in (gemm, comp):
        _arrow(ax, x + w / 2, top, x + w / 2, bot + h)
    _arrow(ax, res[0] + res[1] / 2, top, res[0] + res[1] / 2, bot + h)
    _arrow(ax, comp[0] + comp[1], bot + h / 2, chk[0], bot + h / 2, "predicted cycles",
           color=MUTED, dy=0.06)  # fmt: skip
    y = bot - 0.35
    ax.plot([gemm[0] + gemm[1] / 2, gemm[0] + gemm[1] / 2], [bot, y], color=MUTED, lw=1.3)
    ax.plot([gemm[0] + gemm[1] / 2, chk[0] + 0.5], [y, y], color=MUTED, lw=1.3)
    _arrow(ax, chk[0] + 0.5, y, chk[0] + 0.5, bot, color=MUTED)
    ax.text((comp[0] + comp[1] + chk[0]) / 2, y + 0.06, "expected C", ha="center",
            va="bottom", fontsize=8.5, color=MUTED)  # fmt: skip
    path = out / "flow.png"
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def arch(out: Path) -> Path:
    """Clean, simple block picture of sa_top for the README (no numbers from results)."""
    fig, ax = plt.subplots(figsize=(14.6, 6.4))
    ax.set_xlim(0, 16.2)
    ax.set_ylim(0, 6.6)
    ax.axis("off")
    soft, ctrl, pe, pe_edge, line = "#e8f3f6", "#f3f4f6", "#0b6e8a", "#085a71", "#9fb3c8"

    def box(x, y, w, h, title, sub="", fc=soft, ec=line):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.14",
                                    fc=fc, ec=ec, lw=1.3))  # fmt: skip
        ty = y + h / 2 + (0.17 if sub else 0)
        ax.text(x + w / 2, ty, title, ha="center", va="center", fontsize=13, color=INK,
                weight="bold")  # fmt: skip
        if sub:
            ax.text(x + w / 2, y + h / 2 - 0.2, sub, ha="center", va="center", fontsize=10,
                    color=MUTED)  # fmt: skip

    def path(points, color=INK, ls="-", both=False):
        xs, ys = zip(*points)
        ax.plot(xs[:-1], ys[:-1], color=color, lw=1.6, ls=ls, solid_capstyle="round")
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], mutation_scale=15, lw=1.6,
                                     arrowstyle="<|-|>" if both else "-|>", color=color,
                                     linestyle=ls, shrinkA=0, shrinkB=0))  # fmt: skip

    def label(x, y, text, color=MUTED, ha="center"):
        ax.text(x, y, text, ha=ha, va="center", fontsize=10, color=color)

    # Control: compiler -> controller -> DMA
    box(0.3, 5.0, 2.7, 1.0, "Compiler", "Python", fc="#fdf6e3", ec="#d9c48b")
    box(4.4, 5.0, 2.7, 1.0, "Controller", "schedules the commands", fc=ctrl)
    path([(3.0, 5.5), (4.4, 5.5)], ACCENT)
    label(3.7, 5.75, "commands", ACCENT)
    path([(5.75, 5.0), (5.75, 3.85)], MUTED, ls="--")

    # Memory <-> DMA
    box(0.3, 2.55, 2.7, 1.3, "Memory", "A, B in · C out", fc=ctrl)
    box(4.4, 2.55, 2.7, 1.3, "DMA", "8 bytes / cycle")
    path([(3.0, 3.2), (4.4, 3.2)], both=True)

    # PE array
    gx, gy, cell, gap, n = 12.0, 1.9, 0.26, 0.06, 8
    span = n * cell + (n - 1) * gap
    for r in range(n):
        for c in range(n):
            ax.add_patch(FancyBboxPatch((gx + c * (cell + gap), gy + r * (cell + gap)), cell, cell,
                                        boxstyle="round,pad=0,rounding_size=0.04", fc=pe,
                                        ec=pe_edge, lw=0.6))  # fmt: skip
    cx = gx + span / 2
    ax.text(gx + span + 0.3, gy + span / 2 + 0.3, "8 × 8\nPE array", ha="left", va="center",
            fontsize=13, color=INK, weight="bold", linespacing=1.2)  # fmt: skip
    ax.text(gx + span + 0.3, gy + span / 2 - 0.45, "64 multiply-adds\nper cycle", ha="left",
            va="center", fontsize=10, color=MUTED, linespacing=1.3)  # fmt: skip

    # Buffers
    box(gx, 5.0, span, 0.85, "Weight buffer")
    ix, iy, iw, ih = 8.3, 2.6, 2.4, 1.2
    ax.add_patch(FancyBboxPatch((ix, iy), iw, ih, boxstyle="round,pad=0.02,rounding_size=0.14",
                                fc=soft, ec=line, lw=1.3))  # fmt: skip
    ax.text(ix + iw / 2, iy + 0.88, "Input buffer", ha="center", va="center", fontsize=13,
            color=INK, weight="bold")  # fmt: skip
    ax.plot([ix + iw / 2, ix + iw / 2], [iy + 0.1, iy + 0.55], color=line, lw=1.2)
    label(ix + iw / 4, iy + 0.33, "ping")
    label(ix + 3 * iw / 4, iy + 0.33, "pong")
    box(gx, 0.25, span, 0.95, "Accumulator", "int32")

    # Data paths
    path([(7.1, 3.55), (7.65, 3.55), (7.65, 5.42), (gx, 5.42)])            # load weights
    label(9.8, 5.65, "load weights")
    path([(7.1, 2.95), (ix, 2.95)])                                      # load activations
    label((7.1 + ix) / 2, 2.7, "load A")
    path([(cx, 5.0), (cx, gy + span + 0.05)])                            # weights into array
    label(cx + 0.55, 4.72, "weights ↓")
    path([(ix + iw, 3.2), (gx - 0.05, 3.2)])                             # activations
    label((ix + iw + gx) / 2, 3.45, "activations →")
    path([(cx, gy - 0.05), (cx, 1.2)])                                   # partial sums
    label(cx + 0.75, 1.55, "partial sums ↓")
    path([(gx, 0.72), (5.75, 0.72), (5.75, 2.55)])                       # store
    label(9.0, 0.95, "store C")
    path_ = out / "architecture.png"
    fig.savefig(path_, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path_


def _first_order_a(csv_path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with csv_path.open() as f:
        for r in csv.DictReader(f):
            if r["order"] == "A" and r["shape_id"] not in rows:
                rows[r["shape_id"]] = r
    return rows


def before_after(out: Path, mvp_csv: Path, final_csv: Path) -> Path:
    mvp, final = _first_order_a(mvp_csv), _first_order_a(final_csv)
    shapes = [s for s in SHAPES if s in mvp and s in final]
    u0 = [float(mvp[s]["utilization"]) for s in shapes]
    u1 = [float(final[s]["utilization"]) for s in shapes]
    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    x = range(len(shapes))
    bw = 0.38
    b0 = ax.bar([i - bw / 2 for i in x], u0, bw, color=MVP_C, label="first version (measured)")
    b1 = ax.bar([i + bw / 2 for i in x], u1, bw, color=FINAL_C, label="double buffering (measured)")
    pred = [float(final[s]["predicted_utilization"]) for s in shapes]
    ax.scatter([i + bw / 2 for i in x], pred, marker="_", s=900, color=INK, linewidths=2.2,
               zorder=3, label="predicted by the performance model")  # fmt: skip
    for bars, vals in ((b0, u0), (b1, u1)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center",
                    va="bottom", fontsize=8.5, color=INK)  # fmt: skip
    labels = [f"{s}\n{final[s]['M']}×{final[s]['N']}×{final[s]['K']}" for s in shapes]
    ax.set_xticks(list(x), labels, fontsize=9.5, color=INK)
    ax.set_ylim(0, 0.95)
    ax.set_ylabel("PE utilization (measured)", color=MUTED)
    ax.set_title(f"PE utilization per layer, {final[shapes[0]]['S']} × {final[shapes[0]]['S']} array",
                 color=INK, fontsize=12, loc="left", pad=30)  # fmt: skip
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e7eb")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=9.5, ncol=3)
    path = out / "utilization_before_after.png"
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=REPO / "docs" / "img")
    p.add_argument("--mvp", type=Path, default=REPO / "results" / "perf" / "f5c0a0c.csv")
    p.add_argument("--final", type=Path, default=REPO / "results" / "perf" / "be6f466.csv")
    a = p.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    for path in (arch(a.out), flow(a.out), before_after(a.out, a.mvp, a.final)):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
