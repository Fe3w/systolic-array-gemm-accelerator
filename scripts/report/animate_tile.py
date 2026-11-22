#!/usr/bin/env python3
"""Animate one S = 4 tile of the real sa_array simulation, cycle by cycle (M15).

Input: the VCD from `make demo-waves` (build/demo/tile_s4.vcd: tb/array, seed 5).
Output: docs/img/tile_s4.gif, one frame per clock cycle, showing for each PE
its weight w (u_grid.w_q), the activation it holds (u_grid.a_q, highlighted
while valid) and its partial-sum output Σ (u_grid.psum_q); the skewed values
entering each row on the left (grid_a), the weight rows shifting in on top
(w_load / w_row) and the de-skewed output row of C at the bottom (c_valid /
c_row). Every value is read from the VCD; nothing is computed here except
decoding bits.

The tile shown is the first one in the VCD whose weight load is followed by
`--rows` (default 4) streamed rows. Usage (repo root):
    python3 scripts/report/animate_tile.py [VCD] [--out docs/img/tile_s4.gif]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation, PillowWriter  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
S = 4
PERIOD_PS = 10_000  # 10 ns clock in tb/array
INK, MUTED, ACT, SUM, W, OUT, IDLE = "#1f2933", "#7b8794", "#0b6e8a", "#b5541b", "#5a3d8a", \
    "#1f7a4d", "#f5f7fa"  # fmt: skip


def signals() -> list[str]:
    names = ["clk", "w_load", "w_row", "a_valid", "grid_a", "grid_a_valid", "c_valid", "c_row"]
    for r in range(S):
        for c in range(S):
            names += [f"u_grid.w_q[{r}][{c}]", f"u_grid.a_q[{r}][{c}]",
                      f"u_grid.av_q[{r}][{c}]", f"u_grid.psum_q[{r}][{c}]"]  # fmt: skip
    return names


def read_vcd(path: Path, wanted: list[str]) -> tuple[dict[str, list[str]], dict[str, int], int]:
    """Per-cycle samples (value late in each cycle, after both edges) and widths."""
    ids: dict[str, list[str]] = {}
    widths: dict[str, int] = {}
    scope: list[str] = []
    want = set(wanted)
    cur: dict[str, str] = {}
    samples: dict[str, list[str]] = {n: [] for n in wanted}
    t, cyc = 0, 0

    def flush(upto: int) -> None:
        nonlocal cyc
        while cyc < upto:
            for n in wanted:
                samples[n].append(cur.get(n, "x"))
            cyc += 1

    with open(path) as f:
        for line in f:
            s = line.strip()
            if s.startswith("$scope"):
                scope.append(s.split()[2])
            elif s.startswith("$upscope"):
                scope.pop()
            elif s.startswith("$var"):
                p = s.split()
                if scope and scope[0] == "sa_array":
                    name = ".".join([*scope[1:], p[4]])
                    if name in want:
                        ids.setdefault(p[3], []).append(name)
                        widths[name] = int(p[2])
            elif s.startswith("#"):
                t = int(s[1:])
                flush(t // PERIOD_PS)  # values up to here belong to earlier cycles
            elif s.startswith("b"):
                v, i = s.split()
                for n in ids.get(i, []):
                    cur[n] = v[1:]
            elif s and s[0] in "01xz" and s[1:] in ids:
                for n in ids[s[1:]]:
                    cur[n] = s[0]
    flush(cyc + 1)
    return samples, widths, cyc


def sval(bits: str, width: int) -> int | None:
    if not bits or any(ch not in "01" for ch in bits):
        return None
    x = int(bits, 2)
    return x - (1 << width) if x >> (width - 1) else x


def lane(bits: str, width: int, lane_w: int, i: int) -> int | None:
    v = sval(bits, width)
    if v is None:
        return None
    x = (v % (1 << width)) >> (i * lane_w) & ((1 << lane_w) - 1)
    return x - (1 << lane_w) if x >> (lane_w - 1) else x


def pick_tile(sm: dict[str, list[str]], rows: int) -> tuple[int, int]:
    """First weight load followed by `rows` valid input rows; returns (first, last) cycle."""
    wl, av, cv = sm["w_load"], sm["a_valid"], sm["c_valid"]
    n = len(wl)
    for c in range(1, n):
        if wl[c] == "1" and wl[c - 1] != "1":
            end_w = c
            while end_w < n and wl[end_w] == "1":
                end_w += 1
            if end_w >= n or av[end_w] != "1":
                continue
            k = end_w
            while k < n and av[k] == "1":
                k += 1
            if k - end_w != rows:
                continue
            last = k
            while last < n and cv[last] != "1":
                last += 1
            while last < n and cv[last] == "1":
                last += 1
            return c - 1, min(last + 1, n - 1)
    raise SystemExit(f"no tile with a weight load followed by {rows} rows in the VCD")


def draw(ax, sm: dict, w: dict, c: int, first: int) -> None:
    ax.clear()
    ax.set_xlim(-2.2, S + 1.2)
    ax.set_ylim(S + 2.6, -2.1)  # y grows downward, like the array
    ax.axis("off")
    g = lambda name: sm[name][c]  # noqa: E731
    phase = ("loading weights" if g("w_load") == "1" else
             "streaming rows of A" if g("a_valid") == "1" else
             "row of C leaving" if g("c_valid") == "1" else "draining")  # fmt: skip
    ax.text(-2.1, -1.75, f"cycle {c - first}", fontsize=15, weight="bold", color=INK)
    ax.text(S + 1.1, -1.75, phase, fontsize=13, color=INK, ha="right")
    ax.text(-2.1, -1.25, "w = stationary weight   a = activation (moves right)   "
            "Σ = partial sum (moves down)", fontsize=8.5, color=MUTED)  # fmt: skip
    ax.text(-2.1, -0.95, "Σ lags a by one cycle: multiply and add are two pipeline stages",
            fontsize=8.5, color=MUTED)  # fmt: skip
    # weights entering on top (shift chain)
    if g("w_load") == "1":
        for col in range(S):
            v = lane(g("w_row"), w["w_row"], 8, col)
            ax.text(col + 0.5, -0.45, f"w {v}", ha="center", fontsize=9, color=W, weight="bold")
            ax.annotate("", (col + 0.5, -0.05), (col + 0.5, -0.3),
                        arrowprops={"arrowstyle": "-|>", "color": W})  # fmt: skip
    for r in range(S):
        # value entering row r this cycle (after the input skew)
        valid = g("grid_a_valid") not in ("x", "") and \
            (int(g("grid_a_valid"), 2) >> r) & 1  # fmt: skip
        v = lane(g("grid_a"), w["grid_a"], 8, r)
        ax.text(-1.0, r + 0.5, f"a {v}" if valid else "·", ha="center", va="center",
                fontsize=10, color=ACT if valid else MUTED, weight="bold")  # fmt: skip
        ax.text(-1.9, r + 0.5, f"row {r}\nskew {r}", ha="center", va="center", fontsize=7.5,
                color=MUTED)  # fmt: skip
        if valid:
            ax.annotate("", (-0.02, r + 0.5), (-0.6, r + 0.5),
                        arrowprops={"arrowstyle": "-|>", "color": ACT})  # fmt: skip
        for col in range(S):
            av = g(f"u_grid.av_q[{r}][{col}]") == "1"
            prev_av = c > 0 and sm[f"u_grid.av_q[{r}][{col}]"][c - 1] == "1"
            wv = sval(g(f"u_grid.w_q[{r}][{col}]"), 8)
            a = sval(g(f"u_grid.a_q[{r}][{col}]"), 8)
            ps = sval(g(f"u_grid.psum_q[{r}][{col}]"), 32)
            edge, width = (ACT, 2) if av else ("#cbd2d9", 1)
            ax.add_patch(FancyBboxPatch((col + 0.06, r + 0.06), 0.88, 0.88,
                                        boxstyle="round,pad=0,rounding_size=0.06",
                                        fc="#e3f0f4" if av else IDLE, ec=edge, lw=width))
            ax.text(col + 0.5, r + 0.25, f"w {wv}", ha="center", fontsize=8.5, color=W)
            ax.text(col + 0.5, r + 0.52, f"a {a}" if av else "a ·", ha="center", fontsize=10,
                    color=ACT if av else MUTED, weight="bold" if av else "normal")  # fmt: skip
            ax.text(col + 0.5, r + 0.8, f"Σ {ps}" if prev_av else "Σ ·", ha="center",
                    fontsize=8.5, color=SUM if prev_av else MUTED)  # fmt: skip
    # output row after de-skew
    ax.text(-1.0, S + 1.15, "C row", ha="center", fontsize=9, color=MUTED)
    if g("c_valid") == "1":
        for col in range(S):
            v = lane(g("c_row"), w["c_row"], 32, col)
            ax.text(col + 0.5, S + 1.15, f"{v}", ha="center", fontsize=10, color=OUT,
                    weight="bold")  # fmt: skip
            ax.annotate("", (col + 0.5, S + 0.85), (col + 0.5, S + 0.05),
                        arrowprops={"arrowstyle": "-|>", "color": OUT})  # fmt: skip
    ax.text(-2.1, S + 2.25, "From the RTL simulation of sa_array (S = 4, tb/array, seed 5); "
            "values read from the VCD.", fontsize=7.5, color=MUTED)  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vcd", nargs="?", default=str(REPO / "build" / "demo" / "tile_s4.vcd"))
    ap.add_argument("--out", default=str(REPO / "docs" / "img" / "tile_s4.gif"))
    ap.add_argument("--rows", type=int, default=4, help="rows streamed in the tile to show")
    ap.add_argument("--ms", type=int, default=900, help="milliseconds per cycle")
    args = ap.parse_args()
    sm, widths, _ = read_vcd(Path(args.vcd), signals())
    first, last = pick_tile(sm, args.rows)
    fig, ax = plt.subplots(figsize=(7.2, 7.6), dpi=90)
    fig.patch.set_facecolor("white")
    frames = list(range(first, last + 1))
    anim = FuncAnimation(fig, lambda c: draw(ax, sm, widths, c, first), frames=frames)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    anim.save(out, writer=PillowWriter(fps=1000 / args.ms))
    plt.close(fig)
    print(f"animate_tile: wrote {out} ({len(frames)} cycles, from cycle {first} of the VCD)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
