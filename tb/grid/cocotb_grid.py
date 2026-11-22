"""cocotb tests for rtl/array/sa_grid.sv (the S x S PE grid, no skew), from docs/spec/array.md §6.

The testbench skews the activations by hand, so these tests check the arrival
rule of docs/spec/array.md §4.2 directly: A[m][r] driven into row r in cycle
t0 + m + r reaches PE(r, c) in cycle t0 + m + r + c, and the bottom of column c
shows row m's sum in cycle t0 + m + S + c + 1 (two-stage MAC since M7b, docs/spec/pe.md §4.2).

Cycle numbering is that of tb.common.utils.drive_cycles: stimulus[k] holds the
inputs of cycle k, observed[k] the registered outputs visible in cycle k.
"""

from __future__ import annotations

import cocotb
import numpy as np

from sysarray import golden
from tb.common.utils import (
    drive_cycles,
    get_params,
    get_rng,
    pack,
    rand_signed,
    reset_sync,
    start_clock,
    unpack,
)

DATA_W = 8
ACC_W = 32
OUTPUTS = ["psum_out", "valid_out"]


def _defaults(s: int) -> dict[str, int]:
    return {"w_load": 0, "w_in": 0, "a_in": 0, "a_valid_in": 0}


def _weight_load(weights: list[list[int]]) -> list[dict[str, int]]:
    """S load cycles, last weight row first (docs/spec/array.md §3 rule 1)."""
    s = len(weights)
    return [{"w_load": 1, "w_in": pack(weights[s - 1 - i], DATA_W)} for i in range(s)]


def _skewed_rows(rows: list[list[int]], s: int) -> list[dict[str, int]]:
    """Cycles that present activation row m to grid row r in cycle m + r."""
    n = len(rows) + s - 1
    cycles: list[dict[str, int]] = []
    for t in range(n):
        a = [0] * s
        valid = 0
        for r in range(s):
            m = t - r
            if 0 <= m < len(rows):
                a[r] = rows[m][r]
                valid |= 1 << r
        cycles.append({"a_in": pack(a, DATA_W), "a_valid_in": valid})
    return cycles


async def _setup(dut) -> int:
    s = get_params()["S"]
    start_clock(dut.clk)
    for name, value in _defaults(s).items():
        getattr(dut, name).value = value
    await reset_sync(dut.clk, dut.rst, cycles=2)
    return s


def _check(observed, t0: int, a: np.ndarray, w: np.ndarray, s: int, label: str) -> None:
    """Every column shows exactly the expected rows, each in cycle t0 + m + S + c + 1."""
    expected = golden.gemm(a, w)  # (M, S)
    m_rows = a.shape[0]
    for c in range(s):
        hits = []
        for k, obs in enumerate(observed):
            valid = obs["valid_out"]
            assert valid != -1, f"{label}: valid_out unresolved in cycle {k}"
            if (valid >> c) & 1:
                hits.append(k)
                m = k - t0 - s - c - 1
                assert 0 <= m < m_rows, f"{label}: column {c} valid in unexpected cycle {k}"
                got = unpack(obs["psum_out"], ACC_W, s)[c]
                assert got == expected[m, c], (
                    f"{label}: row {m} column {c} in cycle {k}: got {got}, "
                    f"expected {expected[m, c]}"
                )
        want = [t0 + m + s + c + 1 for m in range(m_rows)]
        assert hits == want, f"{label}: column {c} valid in cycles {hits}, expected {want}"


@cocotb.test()
async def test_impulse(dut) -> None:
    """One row, distinct weights: each column's sum appears exactly in cycle t0 + S + c."""
    s = await _setup(dut)
    w = np.array([[r * s + c + 1 for c in range(s)] for r in range(s)], dtype=np.int64)
    if s * s > 127:
        w = w % 100 + 1
    a = np.array([[r + 2 for r in range(s)]], dtype=np.int64)
    stim = _weight_load(w.tolist())
    t0 = len(stim)
    stim += _skewed_rows(a.tolist(), s)
    stim += [{}] * (2 * s + 2)
    observed = await drive_cycles(dut, stim, OUTPUTS, _defaults(s))
    _check(observed, t0, a, w, s, "impulse")


@cocotb.test()
async def test_random_tile(dut) -> None:
    """Random W and 8 random activation rows, hand-skewed, against golden.gemm."""
    rng = get_rng("test_random_tile")
    s = await _setup(dut)
    m_rows = 8
    w = np.array([[rand_signed(rng, DATA_W) for _ in range(s)] for _ in range(s)])
    a = np.array([[rand_signed(rng, DATA_W) for _ in range(s)] for _ in range(m_rows)])
    stim = _weight_load(w.tolist())
    t0 = len(stim)
    stim += _skewed_rows(a.tolist(), s)
    stim += [{}] * (2 * s + 2)
    observed = await drive_cycles(dut, stim, OUTPUTS, _defaults(s))
    _check(observed, t0, a, w, s, "random tile")
