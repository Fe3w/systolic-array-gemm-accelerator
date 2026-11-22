"""cocotb tests for rtl/array/sa_array.sv (grid + input skew + output de-skew).

Written from docs/spec/array.md §3 (usage rules), §4 (cycle tables) and §6
(test list) before the RTL. The reference model is deliberately simple and
follows the spec, not the RTL:

  * a valid a_row presented in cycle t, with weights W loaded, produces
    c_row = golden.gemm(a_row, W) with c_valid = 1 in exactly cycle t + 2S
    (2S - 1 before the M7b two-stage MAC);
  * no other cycle has c_valid = 1.

Cycle numbering is that of tb.common.utils.drive_cycles: stimulus[k] holds the
inputs of cycle k, observed[k] the outputs visible in cycle k.
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
OUTPUTS = ["c_valid", "c_row"]
DEFAULTS = {"rst": 0, "w_load": 0, "w_row": 0, "a_valid": 0, "a_row": 0}


class Sched:
    """Builds a cycle-by-cycle stimulus and the expected outputs, per the spec."""

    def __init__(self, s: int) -> None:
        self.s = s
        self.stim: list[dict[str, int]] = []
        self.expected: dict[int, list[int]] = {}  # cycle -> expected c_row
        self.weights: np.ndarray | None = None
        self.last_row_cycle: int | None = None

    @property
    def now(self) -> int:
        return len(self.stim)

    def load(self, w: np.ndarray) -> None:
        """S load cycles, last weight row first (§3 rule 1)."""
        for i in range(self.s):
            self.stim.append({"w_load": 1, "w_row": pack(w[self.s - 1 - i].tolist(), DATA_W)})
        self.weights = w

    def row(self, a: list[int]) -> None:
        """Present one valid activation row this cycle."""
        assert self.weights is not None
        t = self.now
        self.stim.append({"a_valid": 1, "a_row": pack(a, DATA_W)})
        out = golden.gemm(np.array([a]), self.weights)[0]
        self.expected[t + 2 * self.s] = [int(v) for v in out]
        self.last_row_cycle = t

    def bubble(self, a: list[int] | None = None) -> None:
        """An idle cycle; a non-zero a_row with a_valid = 0 must be ignored."""
        self.stim.append({"a_valid": 0, "a_row": pack(a or [0] * self.s, DATA_W)})

    def idle(self, n: int) -> None:
        self.stim += [{} for _ in range(n)]

    def earliest_reload(self) -> int:
        """§3 rule 3: first w_load no earlier than t_last + 2S - 2."""
        assert self.last_row_cycle is not None
        return self.last_row_cycle + 2 * self.s - 2

    def drain(self) -> None:
        self.idle(2 * self.s + 2)


def _check(observed: list[dict[str, int]], expected: dict[int, list[int]], s: int, label: str):
    valid_cycles = []
    for k, obs in enumerate(observed):
        assert obs["c_valid"] != -1, f"{label}: c_valid unresolved in cycle {k}"
        if obs["c_valid"]:
            valid_cycles.append(k)
            assert k in expected, f"{label}: unexpected c_valid in cycle {k}"
            got = unpack(obs["c_row"], ACC_W, s)
            assert got == expected[k], f"{label}: cycle {k}: c_row={got}, expected {expected[k]}"
    want = sorted(expected)
    assert valid_cycles == want, f"{label}: c_valid in cycles {valid_cycles}, expected {want}"


async def _setup(dut) -> int:
    s = get_params()["S"]
    start_clock(dut.clk)
    for name, value in DEFAULTS.items():
        getattr(dut, name).value = value
    await reset_sync(dut.clk, dut.rst, cycles=2)
    return s


async def _run(dut, sched: Sched, label: str) -> list[dict[str, int]]:
    observed = await drive_cycles(dut, sched.stim, OUTPUTS, DEFAULTS)
    _check(observed, sched.expected, sched.s, label)
    dut._log.info("%s: %d output rows checked", label, len(sched.expected))
    return observed


def _rand_matrix(rng, rows: int, cols: int) -> np.ndarray:
    return np.array([[rand_signed(rng, DATA_W) for _ in range(cols)] for _ in range(rows)])


@cocotb.test()
async def test_directed(dut) -> None:
    """Identity, single non-zero weight, all -128, all 127, mixed signs (§6 test 1)."""
    s = await _setup(dut)
    sched = Sched(s)
    ramp = [((7 * i + 3) % 256) - 128 for i in range(s)]

    sched.load(np.eye(s, dtype=np.int64))  # identity: c_row == a_row
    for a in (ramp, [-128] * s, [127] * s):
        sched.row(a)

    w = np.zeros((s, s), dtype=np.int64)
    w[s - 1, 0] = -7  # single non-zero weight: only column 0 sees row s-1's input
    sched.idle(2 * s)
    sched.load(w)
    sched.row(ramp)
    sched.row([5] * s)

    sched.idle(2 * s)
    sched.load(np.full((s, s), -128, dtype=np.int64))
    sched.row([-128] * s)  # every output = S * 16384
    sched.row([127] * s)

    sched.idle(2 * s)
    sched.load(np.full((s, s), 127, dtype=np.int64))
    sched.row([127] * s)
    sched.row([-128] * s)

    sched.idle(2 * s)
    mixed = np.array([[(-1) ** (r + c) * (100 + r + c) for c in range(s)] for r in range(s)])
    sched.load(mixed)
    sched.row([(-1) ** r * (120 - r) for r in range(s)])
    sched.drain()
    await _run(dut, sched, "directed")


@cocotb.test()
async def test_latency_exact(dut) -> None:
    """One row: c_valid exactly 2S cycles after a_valid, exactly once (§6 test 2)."""
    s = await _setup(dut)
    sched = Sched(s)
    sched.load(np.eye(s, dtype=np.int64))
    t0 = sched.now
    sched.row(list(range(1, s + 1)))
    sched.drain()
    observed = await _run(dut, sched, "latency")
    hits = [k for k, o in enumerate(observed) if o["c_valid"] == 1]
    assert hits == [t0 + 2 * s], f"c_valid in {hits}, expected [{t0 + 2 * s}]"
    dut._log.info("S=%d: latency a_row -> c_row = %d cycles", s, hits[0] - t0)


@cocotb.test()
async def test_random_tiles(dut) -> None:
    """Random tiles with M in {1, 4, 7, 16}, rows back to back (§6 test 3)."""
    rng = get_rng("test_random_tiles")
    s = await _setup(dut)
    for m in (1, 4, 7, 16):
        sched = Sched(s)
        sched.load(_rand_matrix(rng, s, s))
        for row in _rand_matrix(rng, m, s):
            sched.row(row.tolist())
        sched.drain()
        await _run(dut, sched, f"random M={m}")


@cocotb.test()
async def test_bubbles(dut) -> None:
    """Random a_valid = 0 cycles (with garbage a_row) between valid rows (§6 test 4)."""
    rng = get_rng("test_bubbles")
    s = await _setup(dut)
    sched = Sched(s)
    sched.load(_rand_matrix(rng, s, s))
    for _ in range(40):
        row = [rand_signed(rng, DATA_W) for _ in range(s)]
        if rng.random() < 0.6:
            sched.row(row)
        else:
            sched.bubble(row)
    sched.drain()
    await _run(dut, sched, "bubbles")


@cocotb.test()
async def test_back_to_back_earliest_reload(dut) -> None:
    """Second tile's load starts at the earliest legal cycle t_last + 2S - 2 (§6 test 5)."""
    rng = get_rng("test_back_to_back_earliest_reload")
    s = await _setup(dut)
    sched = Sched(s)
    for _tile in range(3):
        sched.load(_rand_matrix(rng, s, s))
        for row in _rand_matrix(rng, 5, s):
            sched.row(row.tolist())
        sched.idle(sched.earliest_reload() - sched.now)
    sched.drain()
    await _run(dut, sched, "back-to-back")


@cocotb.test()
async def test_reload_one_cycle_early_corrupts(dut) -> None:
    """Reload at t_last + 2S - 3 corrupts exactly c_row[S-1] of the last row (§6 test 6).

    Derivation (§3 rule 3, D-012): the first load edge, at the end of cycle
    t_last + 2S - 3, shifts the old W[S-2][S-1] into PE(S-1, S-1), whose last MAC
    for the last row happens in cycle t_last + 2S - 2. Every other PE finished its
    last MAC by cycle t_last + 2S - 3, before the edge. So the last row's column
    S-1 equals the golden value with W[S-1][S-1] replaced by W[S-2][S-1].
    """
    s = await _setup(dut)
    if s < 2:
        return
    sched = Sched(s)
    w = np.array([[r * s + c + 1 for c in range(s)] for r in range(s)], dtype=np.int64)
    sched.load(w)
    sched.row([3] * s)
    last = [1 + r for r in range(s)]  # A[last][S-1] = S != 0
    sched.row(last)
    t_out = sched.now - 1 + 2 * s
    sched.idle(sched.earliest_reload() - 1 - sched.now)
    sched.load(np.zeros((s, s), dtype=np.int64))
    sched.drain()
    corrupted_w = w.copy()
    corrupted_w[s - 1, s - 1] = w[s - 2, s - 1]
    want = golden.gemm(np.array([last]), corrupted_w)[0]
    assert want[s - 1] != sched.expected[t_out][s - 1], "test vector cannot show corruption"
    sched.expected[t_out] = [int(v) for v in want]
    await _run(dut, sched, "early reload")


@cocotb.test()
async def test_reset_mid_stream(dut) -> None:
    """Reset drops rows in flight, keeps weights; later rows and a reload work (§6 test 7)."""
    rng = get_rng("test_reset_mid_stream")
    s = await _setup(dut)
    sched = Sched(s)
    w = _rand_matrix(rng, s, s)
    sched.load(w)
    rows = _rand_matrix(rng, 6, s)
    for row in rows:
        sched.row(row.tolist())
    tr = sched.now - 3  # reset asserted in the cycle the 4th row is presented
    sched.stim[tr]["rst"] = 1
    # A reset in cycle tr clears every valid flop at the edge ending cycle tr. Rows
    # presented in cycles <= tr (including tr itself) whose output is due in cycle
    # tr + 1 or later are dropped. Rows presented after tr are captured after the
    # reset edge and must come out normally.
    lat = 2 * s
    for t_out in [k for k in sched.expected if k >= tr + 1 and k - lat <= tr]:
        del sched.expected[t_out]
    sched.idle(2 * s)
    for row in _rand_matrix(rng, 3, s):  # weights survive reset (w_q is not reset)
        sched.row(row.tolist())
    sched.idle(2 * s)
    sched.load(_rand_matrix(rng, s, s))
    for row in _rand_matrix(rng, 3, s):
        sched.row(row.tolist())
    sched.drain()
    await _run(dut, sched, "reset mid-stream")
