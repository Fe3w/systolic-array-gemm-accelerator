#!/usr/bin/env python3
"""Architecture figures for the README and docs/ARCHITECTURE.md (M14).

  docs/img/block_diagram.png  blocks of sa_top and the data paths between them
  docs/img/dataflow_s4.png    S = 4 weight-stationary dataflow: input skew, the
                              cycle each PE multiplies row m, output de-skew

The cycle labels come from docs/spec/array.md §4.2 (A[m][r] reaches PE(r, c) in
cycle t0 + r + c; every column shows row m in cycle t0 + 2S), which
`results/latency/` confirms in simulation. Usage (repo root):
    python3 scripts/report/figures.py [--out docs/img]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
INK, MUTED, ACCENT, FILL, FILL2 = "#1f2933", "#52606d", "#0b6e8a", "#e3f0f4", "#f5f7fa"


def _box(ax, x, y, w, h, text, fill=FILL, size=10, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fill, ec=INK, lw=1.2))  # fmt: skip
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK,
            weight=weight)  # fmt: skip


def _arrow(ax, x0, y0, x1, y1, text="", color=INK, both=False, offset=(0, 0.12)):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="<|-|>" if both else "-|>",
                                 mutation_scale=12, lw=1.2, color=color))  # fmt: skip
    if text:
        ax.text((x0 + x1) / 2 + offset[0], (y0 + y1) / 2 + offset[1], text, ha="center",
                va="bottom", fontsize=8, color=MUTED)  # fmt: skip


def block_diagram(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 5.6)
    ax.axis("off")
    _box(ax, 0.2, 4.4, 2.6, 0.8, "host / compiler\nsysarray.tile()", fill=FILL2)
    _box(ax, 3.6, 4.4, 3.4, 0.8, "sa_ctrl\ndispatcher, checks, counters", weight="bold")
    _box(ax, 0.2, 1.9, 2.6, 1.2, "memory\n(8 B per row beat,\nvalid/ready)", fill=FILL2)
    _box(ax, 3.6, 1.9, 1.6, 1.2, "sa_dma")
    _box(ax, 6.0, 3.2, 2.0, 0.7, "weight buffer\nS × S int8", size=9)
    _box(ax, 6.0, 2.2, 2.0, 0.8, "input buffer\n2 × 128 rows (ping-pong)", size=9)
    _box(ax, 6.0, 0.5, 2.0, 0.9, "accumulator\n256 rows × S int32\nread-modify-write", size=9)
    _box(ax, 8.6, 2.2, 2.2, 1.7, "sa_feeder\n+ sa_array\nS × S PEs\n(skew / de-skew)",
         weight="bold")  # fmt: skip
    _arrow(ax, 2.8, 4.8, 3.6, 4.8, "commands")
    _arrow(ax, 2.8, 2.5, 3.6, 2.5, "", both=True)
    _arrow(ax, 5.2, 2.8, 6.0, 3.5, "")
    _arrow(ax, 5.2, 2.6, 6.0, 2.6, "LOAD")
    _arrow(ax, 6.0, 0.9, 4.4, 1.9, "STORE", offset=(-0.4, -0.1))
    _arrow(ax, 8.0, 3.55, 8.6, 3.55, "")
    _arrow(ax, 8.0, 2.6, 8.6, 2.6, "")
    _arrow(ax, 9.7, 2.2, 8.0, 0.95, "C rows + tag", offset=(0.55, -0.15))
    _arrow(ax, 4.4, 4.4, 4.4, 3.1, "", color=ACCENT)
    _arrow(ax, 6.2, 4.4, 9.2, 3.9, "", color=ACCENT)
    ax.text(4.5, 3.75, "DMA unit", color=ACCENT, fontsize=8)
    ax.text(7.9, 4.25, "feeder unit", color=ACCENT, fontsize=8)
    ax.text(5.5, 0.1, "Both units run concurrently (M13); the dispatcher orders dependent "
            "commands (docs/spec/ctrl.md §2).", ha="center", fontsize=8.5, color=MUTED)  # fmt: skip
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def dataflow(path: Path, s: int = 4) -> None:
    fig, ax = plt.subplots(figsize=(9, 7.4))
    ax.set_xlim(-2.6, s + 0.8)
    ax.set_ylim(-1.5, s + 2.0)
    ax.invert_yaxis()
    ax.axis("off")
    for r in range(s):
        ax.text(-2.5, r + 0.5, f"A[m][{r}]", va="center", fontsize=10, color=INK)
        _box(ax, -1.6, r + 0.2, 1.1, 0.6, f"skew D={r}", fill=FILL2, size=8.5)
        _arrow(ax, -0.5, r + 0.5, -0.05, r + 0.5)
        for c in range(s):
            _box(ax, c + 0.05, r + 0.05, 0.9, 0.9, f"B[{r}][{c}]\nt0+{r + c}", size=9)
            if c < s - 1:
                _arrow(ax, c + 0.95, r + 0.35, c + 1.05, r + 0.35, color=ACCENT)
            if r < s - 1:
                _arrow(ax, c + 0.65, r + 0.95, c + 0.65, r + 1.05, color=INK)
    for c in range(s):
        _box(ax, c + 0.1, s + 0.2, 0.8, 0.55, f"D={s - 1 - c}", fill=FILL2, size=8.5)
        _arrow(ax, c + 0.5, s + 0.75, c + 0.5, s + 1.15)
        ax.text(c + 0.5, s + 1.28, f"C[m][{c}]", ha="center", va="top", fontsize=9)
    ax.text(s / 2, -1.15, f"Weight-stationary S = {s}: PE(r, c) holds B[r][c] and multiplies "
            "A[m][r] in cycle t0 + r + c", ha="center", fontsize=10.5, color=INK)  # fmt: skip
    ax.text(s / 2, -0.7, "activations move right (blue), partial sums move down (black); "
            f"row m leaves de-skewed in cycle t0 + 2S = t0 + {2 * s}", ha="center", fontsize=9,
            color=MUTED)  # fmt: skip
    ax.text(s / 2, s + 1.85, "Source: docs/spec/array.md §4.2; latency 2S measured in "
            "results/latency/latency_d4aedec.csv", ha="center", fontsize=8.5,
            color=MUTED)  # fmt: skip
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "docs" / "img"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    block_diagram(out / "block_diagram.png")
    dataflow(out / "dataflow_s4.png")
    print(f"figures: wrote {out / 'block_diagram.png'} and {out / 'dataflow_s4.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
