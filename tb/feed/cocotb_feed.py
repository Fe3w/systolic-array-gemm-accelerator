"""cocotb tests for rtl/array/sa_feed_top.sv (buffers + sa_feeder + sa_array).

Written from docs/spec/buffers.md §3–§4 and §6 before the feeder RTL. The
reference model follows the spec's cycle tables, with `start` in cycle t:

  LOAD_W : busy in t+1 .. t+S+2, done in t+S+2; the array holds the weight
           buffer's tile from then on.
  STREAM : busy in t+1 .. t+M+2, done in t+M+2 (rows = 0: busy and done in t+1);
           input row base+j reaches the array in cycle t+3+j, so its output
           (golden.gemm with the loaded tile) has c_valid in cycle t+3+j+2S.
  (M7b output register, D-022: one cycle later than M5's t+2+j.)
  start while busy (cycle t): ignored, start_dropped in cycle t+1.

Cycle numbering as in tb.common.utils.drive_cycles.
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
LOAD_W, STREAM = 0, 1
DEFAULTS = {
    "rst": 0,
    "wb_we": 0,
    "wb_waddr": 0,
    "wb_wdata": 0,
    "ib_we": 0,
    "ib_waddr": 0,
    "ib_wdata": 0,
    "start": 0,
    "op": 0,
    "base": 0,
    "rows": 0,
}
OUTPUTS = ["busy", "done", "start_dropped", "c_valid", "c_row"]


class FeedModel:
    """Builds stimulus and the expected per-cycle outputs from the spec."""

    def __init__(self, s: int, in_depth: int) -> None:
        self.s, self.in_depth = s, in_depth
        self.stim: list[dict[str, int]] = []
        self.wbuf = np.zeros((s, s), dtype=np.int64)
        self.ibuf = np.zeros((in_depth, s), dtype=np.int64)
        self.weights: np.ndarray | None = None
        self.out: dict[int, list[int]] = {}
        self.done: set[int] = set()
        self.busy: set[int] = set()
        self.dropped: set[int] = set()
        self.busy_until = -1  # last busy cycle of the running command
        self.last_a_valid: int | None = None

    @property
    def now(self) -> int:
        return len(self.stim)

    def _set(self, cycle: int, **inputs: int) -> None:
        while len(self.stim) <= cycle:
            self.stim.append({})
        self.stim[cycle].update(inputs)

    def write_weights(self, w: np.ndarray) -> None:
        for k in range(self.s):
            self.stim.append({"wb_we": 1, "wb_waddr": k, "wb_wdata": pack(w[k].tolist(), DATA_W)})
        self.wbuf = w.copy()

    def write_inputs(self, base: int, rows: np.ndarray) -> None:
        for j, row in enumerate(rows):
            self.stim.append(
                {"ib_we": 1, "ib_waddr": base + j, "ib_wdata": pack(row.tolist(), DATA_W)}
            )
            self.ibuf[base + j] = row

    def idle_until(self, cycle: int) -> None:
        while self.now < cycle:
            self.stim.append({})

    def free_at(self) -> int:
        """First cycle in which busy = 0 again."""
        return self.busy_until + 1

    def load_w(self, rows: int = 0) -> int:
        """LOAD_W; rows = number of real weight rows (0 = all S), the rest load as zero."""
        t = max(self.now, self.free_at())
        self.idle_until(t)
        self._set(t, start=1, op=LOAD_W, rows=rows)
        self.busy.update(range(t + 1, t + self.s + 3))
        self.done.add(t + self.s + 2)
        self.busy_until = t + self.s + 2
        self.weights = self.wbuf.copy()
        if 0 < rows < self.s:
            self.weights[rows:] = 0
        return t

    def earliest_reload_start(self) -> int:
        """docs/spec/array.md §3 rule 3: first w_load (t+3) >= t_last + 2S - 2."""
        if self.last_a_valid is None:
            return self.free_at()
        return max(self.free_at(), self.last_a_valid + 2 * self.s - 5)

    def stream(self, base: int, rows: int) -> int:
        assert self.weights is not None
        t = max(self.now, self.free_at())
        self.idle_until(t)
        self._set(t, start=1, op=STREAM, base=base, rows=rows)
        end = t + rows + 2 if rows > 0 else t + 1
        self.busy.update(range(t + 1, end + 1))
        self.done.add(end)
        self.busy_until = end
        for j in range(rows):
            a = self.ibuf[base + j]
            self.out[t + 3 + j + 2 * self.s] = [
                int(v) for v in golden.gemm(a[None, :], self.weights)[0]
            ]
            self.last_a_valid = t + 3 + j
        return t

    def poke_start_while_busy(self, cycle: int) -> None:
        assert cycle in self.busy
        self._set(cycle, start=1, op=STREAM, base=0, rows=1)
        self.dropped.add(cycle + 1)

    def drain(self) -> None:
        self.idle_until(max([self.now, self.busy_until + 1, *self.out]) + 3)


def _check(observed, model: FeedModel, label: str) -> None:
    s = model.s
    for k, obs in enumerate(observed):
        for name in ("busy", "done", "start_dropped", "c_valid"):
            assert obs[name] != -1, f"{label}: {name} unresolved in cycle {k}"
        assert obs["busy"] == int(k in model.busy), f"{label}: busy={obs['busy']} in cycle {k}"
        assert obs["done"] == int(k in model.done), f"{label}: done={obs['done']} in cycle {k}"
        assert obs["start_dropped"] == int(k in model.dropped), f"{label}: start_dropped cycle {k}"
        assert obs["c_valid"] == int(k in model.out), f"{label}: c_valid={obs['c_valid']} cycle {k}"
        if obs["c_valid"]:
            got = unpack(obs["c_row"], ACC_W, s)
            assert got == model.out[k], f"{label}: cycle {k}: c_row={got}, expected {model.out[k]}"


async def _setup(dut) -> tuple[int, int]:
    p = get_params()
    start_clock(dut.clk)
    for name, value in DEFAULTS.items():
        getattr(dut, name).value = value
    await reset_sync(dut.clk, dut.rst, cycles=2)
    return p["S"], p["IN_DEPTH"]


async def _run(dut, model: FeedModel, label: str) -> None:
    model.drain()
    observed = await drive_cycles(dut, model.stim, OUTPUTS, DEFAULTS)
    _check(observed, model, label)
    dut._log.info("%s: %d output rows checked", label, len(model.out))


def _rand(rng, rows: int, cols: int) -> np.ndarray:
    return np.array([[rand_signed(rng, DATA_W) for _ in range(cols)] for _ in range(rows)])


@cocotb.test()
async def test_load_then_stream(dut) -> None:
    """LOAD_W then STREAM for M in {1, 8, 64, IN_DEPTH} (§6 tests 1-2)."""
    rng = get_rng("test_load_then_stream")
    s, in_depth = await _setup(dut)
    for m in sorted({1, 8, min(64, in_depth), in_depth}):
        model = FeedModel(s, in_depth)
        model.write_weights(_rand(rng, s, s))
        model.write_inputs(0, _rand(rng, m, s))
        t_load = model.load_w()
        model.stream(0, m)
        await _run(dut, model, f"M={m}")
        last_out = max(model.out)
        # docs/spec/buffers.md §4.3: last output in cycle t_load + M + 3S + 5.
        assert last_out == t_load + m + 3 * s + 5, f"M={m}: last output {last_out - t_load}"


@cocotb.test()
async def test_base_offset_and_zero_rows(dut) -> None:
    """STREAM from a non-zero base, and STREAM with rows = 0 (§6 test 3)."""
    rng = get_rng("test_base_offset_and_zero_rows")
    s, in_depth = await _setup(dut)
    model = FeedModel(s, in_depth)
    model.write_weights(_rand(rng, s, s))
    base = in_depth // 2 + 1
    m = min(5, in_depth - base)
    model.write_inputs(base, _rand(rng, m, s))
    model.load_w()
    model.stream(0, 0)
    model.stream(base, m)
    model.stream(0, 0)
    await _run(dut, model, "base/zero-rows")


@cocotb.test()
async def test_two_tiles_earliest_reload(dut) -> None:
    """Tile 1, reload at the earliest legal cycle, tile 2 (§6 test 4)."""
    rng = get_rng("test_two_tiles_earliest_reload")
    s, in_depth = await _setup(dut)
    model = FeedModel(s, in_depth)
    m = min(6, in_depth // 2)
    model.write_weights(_rand(rng, s, s))
    model.write_inputs(0, _rand(rng, 2 * m, s))
    model.load_w()
    model.stream(0, m)
    w2 = _rand(rng, s, s)
    model.write_weights(w2)  # buffer write while the array drains: allowed
    model.idle_until(model.earliest_reload_start())
    model.load_w()
    model.stream(m, m)
    await _run(dut, model, "two tiles")


@cocotb.test()
async def test_start_while_busy_dropped(dut) -> None:
    """start while busy is ignored and pulses start_dropped; the command finishes (§6 test 5)."""
    rng = get_rng("test_start_while_busy_dropped")
    s, in_depth = await _setup(dut)
    model = FeedModel(s, in_depth)
    m = min(8, in_depth)
    model.write_weights(_rand(rng, s, s))
    model.write_inputs(0, _rand(rng, m, s))
    t = model.load_w()
    model.poke_start_while_busy(t + 2)
    t = model.stream(0, m)
    model.poke_start_while_busy(t + 1)
    model.poke_start_while_busy(t + m + 2)  # in the done cycle: still busy
    await _run(dut, model, "start while busy")


@cocotb.test()
async def test_partial_weight_load(dut) -> None:
    """LOAD_W with rows = r < S presents zero for weight rows r..S-1 (M11b issue 7)."""
    rng = get_rng("test_partial_weight_load")
    s, in_depth = await _setup(dut)
    m = min(6, in_depth)
    for r in (1, s - 1):
        model = FeedModel(s, in_depth)
        model.write_weights(_rand(rng, s, s))  # stale non-zero rows must not leak through
        model.write_inputs(0, _rand(rng, m, s))
        model.load_w(rows=r)
        model.stream(0, m)
        await _run(dut, model, f"partial r={r}")
