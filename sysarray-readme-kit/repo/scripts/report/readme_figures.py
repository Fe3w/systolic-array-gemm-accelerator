#!/usr/bin/env python3
"""README figures (portfolio README rework).

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
    b0 = ax.bar([i - bw / 2 for i in x], u0, bw, color=MVP_C, label="MVP (no overlap)")
    b1 = ax.bar([i + bw / 2 for i in x], u1, bw, color=FINAL_C, label="double buffering")
    for bars, vals in ((b0, u0), (b1, u1)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center",
                    va="bottom", fontsize=8.5, color=INK)  # fmt: skip
    labels = [f"{s}\n{final[s]['M']}×{final[s]['N']}×{final[s]['K']}" for s in shapes]
    ax.set_xticks(list(x), labels, fontsize=8.5, color=INK)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("PE utilization (measured)", color=MUTED)
    ax.set_title(f"SysArray S = {final[shapes[0]]['S']}: PE utilization, MVP vs double buffering"
                 f" ({mvp_csv.name} → {final_csv.name})", color=INK, fontsize=11, loc="left")  # fmt: skip
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e7eb")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right", fontsize=9)
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
    for path in (flow(a.out), before_after(a.out, a.mvp, a.final)):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
