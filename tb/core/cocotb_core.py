"""End-to-end cocotb tests for rtl/core/sa_core.sv, from docs/spec/acc.md §2-§3.

A small GEMM driver in Python issues DMA descriptors and feeder commands for
C = A @ B (N, K multiples of S), following the sequencing rules of spec §2:
  1. LOAD_W start >= previous STREAM done + 2S - 5 (array reload rule, M7b timing);
  2. STORE start  >= last STREAM done + 2S + 3   (last accumulator write, M11b 3-stage RMW).
The memory model (tb/common/memory.py) applies random stalls; a protocol checker
watches both request channels every cycle. C in memory is compared with golden.gemm.
"""

from __future__ import annotations

import random

import cocotb
import numpy as np
from cocotb.triggers import FallingEdge, Timer

from sysarray import golden
from tb.common.memory import Memory
from tb.common.utils import get_params, get_rng, reset_sync, start_clock

LOAD, STORE = 0, 1
WBUF, IBUF = 0, 1
LOAD_W, STREAM = 0, 1
OVERWRITE, ACCUMULATE = 0, 1
A_BASE, B_BASE, C_BASE = 0x0000, 0x4000, 0x8000
INPUTS = {
    "dma_start": 0, "dma_dir": 0, "dma_target": 0, "dma_mem_addr": 0, "dma_mem_stride": 0,
    "dma_rows": 0, "dma_buf_addr": 0, "f_start": 0, "f_op": 0, "f_base": 0, "f_rows": 0,
    "acc_mode": 0, "acc_base": 0,
}  # fmt: skip
STATUS = ("dma_busy", "dma_done", "dma_dropped", "f_busy", "f_done", "f_dropped")


def _u(sig) -> int:
    v = sig.value
    return v.to_unsigned() if hasattr(v, "to_unsigned") else int(v)


class Core:
    def __init__(self, dut, mem: Memory, s: int) -> None:
        self.dut, self.mem, self.s = dut, mem, s
        self.cycle = 0
        self.prev: dict[str, tuple] = {}
        self.violations: list[str] = []

    def _protocol(self, name: str, valid: int, payload: tuple, ready: int) -> None:
        p = self.prev.get(name)
        if p and p[0] and not p[2] and (not valid or payload != p[1]):
            self.violations.append(f"cycle {self.cycle}: {name} dropped/changed while stalled")
        self.prev[name] = (valid, payload, ready)

    async def tick(self, **inputs: int) -> dict[str, int]:
        d = self.dut
        await FallingEdge(d.clk)
        rd = (_u(d.rd_req_valid), _u(d.rd_req_addr))
        wr = (_u(d.wr_req_valid), _u(d.wr_req_addr), _u(d.wr_req_data))
        out = self.mem.step({"rd_req_valid": rd[0], "rd_req_addr": rd[1],
                             "rd_resp_ready": _u(d.rd_resp_ready), "wr_req_valid": wr[0],
                             "wr_req_addr": wr[1], "wr_req_data": wr[2]})  # fmt: skip
        for k, v in {**INPUTS, **inputs, **out}.items():
            getattr(d, k).value = v
        self._protocol("rd_req", rd[0], rd[1:], out["rd_req_ready"])
        self._protocol("wr_req", wr[0], wr[1:], out["wr_req_ready"])
        await Timer(1, unit="ns")
        st = {k: _u(getattr(d, k)) for k in STATUS}
        st["cycle"] = self.cycle
        assert not st["dma_dropped"] and not st["f_dropped"], f"command dropped: {st}"
        self.cycle += 1
        return st

    async def wait_until(self, cycle: int) -> None:
        while self.cycle < cycle:
            await self.tick()

    async def command(self, done_key: str, **inputs: int) -> int:
        """Issue one command (start pulse) and return the cycle of its done."""
        st = await self.tick(**inputs)
        for _ in range(100000):
            if st[done_key]:
                return st["cycle"]
            st = await self.tick()
        raise AssertionError(f"command {inputs} never finished")

    async def dma(self, **desc: int) -> int:
        return await self.command(
            "dma_done", dma_start=1, **{f"dma_{k}": v for k, v in desc.items()}
        )

    async def feed(self, **cmd: int) -> int:
        return await self.command("f_done", f_start=1, **cmd)


async def run_gemm(core: Core, a: np.ndarray, b: np.ndarray) -> None:
    s = core.s
    m, k = a.shape
    n = b.shape[1]
    assert k % s == 0 and n % s == 0
    core.mem.data[A_BASE : A_BASE + m * k] = a.astype(np.int8).tobytes()
    core.mem.data[B_BASE : B_BASE + k * n] = b.astype(np.int8).tobytes()
    last_stream_done = None
    for n0 in range(0, n, s):
        for kt, k0 in enumerate(range(0, k, s)):
            await core.dma(dir=LOAD, target=WBUF, mem_addr=B_BASE + k0 * n + n0,
                           mem_stride=n, rows=s, buf_addr=0)  # fmt: skip
            await core.dma(dir=LOAD, target=IBUF, mem_addr=A_BASE + k0, mem_stride=k,
                           rows=m, buf_addr=0)  # fmt: skip
            if last_stream_done is not None:  # rule 1: array reload after drain
                await core.wait_until(last_stream_done + 2 * s - 5)
            await core.feed(f_op=LOAD_W)
            last_stream_done = await core.feed(f_op=STREAM, f_base=0, f_rows=m,
                                               acc_mode=OVERWRITE if kt == 0 else ACCUMULATE,
                                               acc_base=0)  # fmt: skip
        await core.wait_until(last_stream_done + 2 * s + 3)  # rule 2: last acc write done
        await core.dma(dir=STORE, mem_addr=C_BASE + 4 * n0, mem_stride=4 * n, rows=m, buf_addr=0)
    c = np.frombuffer(bytes(core.mem.data[C_BASE : C_BASE + 4 * m * n]), dtype="<i4").reshape(m, n)
    expected = golden.gemm(a, b)
    bad = np.argwhere(c != expected)
    assert bad.size == 0, f"C mismatch at {bad[:5].tolist()}: got {c[tuple(bad[0])]}, " \
                          f"expected {expected[tuple(bad[0])]}"  # fmt: skip
    assert not core.violations, core.violations[:3]


async def _setup(dut, rng, stalls: float) -> Core:
    p = get_params()
    start_clock(dut.clk)
    for name, v in INPUTS.items():
        getattr(dut, name).value = v
    for name in ("rd_req_ready", "rd_resp_valid", "rd_resp_data", "wr_req_ready"):
        getattr(dut, name).value = 0
    await reset_sync(dut.clk, dut.rst, cycles=2)
    mem = Memory(1 << 16, p["S"], read_latency=3, max_outstanding=4,
                 rng=random.Random(rng.getrandbits(32)), req_stall=stalls,
                 resp_stall=stalls, wr_stall=stalls)  # fmt: skip
    return Core(dut, mem, p["S"])


def _rand(rng, rows: int, cols: int) -> np.ndarray:
    return np.array([[rng.randint(-128, 127) for _ in range(cols)] for _ in range(rows)])


@cocotb.test()
async def test_one_tile(dut) -> None:
    """One S x S weight tile, M in {1, 8, 37}, memory with stalls."""
    rng = get_rng("test_one_tile")
    core = await _setup(dut, rng, stalls=0.2)
    s = core.s
    for m in (1, 8, 37):
        await run_gemm(core, _rand(rng, m, s), _rand(rng, s, s))
        dut._log.info("one tile M=%d: C matches golden", m)


@cocotb.test()
async def test_two_k_slices_two_n_tiles(dut) -> None:
    """K = 2S with ACCUMULATE, N = 2S (two output column tiles), M = 13."""
    rng = get_rng("test_two_k_slices_two_n_tiles")
    core = await _setup(dut, rng, stalls=0.2)
    s = core.s
    await run_gemm(core, _rand(rng, 13, 2 * s), _rand(rng, 2 * s, 2 * s))
    dut._log.info("M=13 K=%d N=%d: C matches golden, %d cycles", 2 * s, 2 * s, core.cycle)


@cocotb.test()
async def test_corner_values(dut) -> None:
    """All -128 inputs, K = 2S: every C entry = 2S * 16384."""
    rng = get_rng("test_corner_values")
    core = await _setup(dut, rng, stalls=0.0)
    s = core.s
    await run_gemm(core, np.full((5, 2 * s), -128), np.full((2 * s, s), -128))


@cocotb.test()
async def test_back_to_back_streams(dut) -> None:
    """STREAMs started the cycle after the previous one's done, with different
    accumulator bases and modes (M13: per-row accumulator tags, no D-024 gap)."""
    rng = get_rng("test_back_to_back_streams")
    core = await _setup(dut, rng, stalls=0.0)
    s = core.s
    m = 5
    a, w = _rand(rng, 2 * m, s), _rand(rng, s, s)
    core.mem.data[A_BASE : A_BASE + 2 * m * s] = a.astype(np.int8).tobytes()
    core.mem.data[B_BASE : B_BASE + s * s] = w.astype(np.int8).tobytes()
    await core.dma(dir=LOAD, target=WBUF, mem_addr=B_BASE, mem_stride=s, rows=s, buf_addr=0)
    await core.dma(dir=LOAD, target=IBUF, mem_addr=A_BASE, mem_stride=s, rows=2 * m, buf_addr=0)
    await core.feed(f_op=LOAD_W)
    hi = 16
    await core.feed(f_op=STREAM, f_base=0, f_rows=m, acc_mode=OVERWRITE, acc_base=0)
    await core.feed(f_op=STREAM, f_base=m, f_rows=m, acc_mode=OVERWRITE, acc_base=hi)
    done = await core.feed(f_op=STREAM, f_base=0, f_rows=m, acc_mode=ACCUMULATE, acc_base=hi)
    await core.wait_until(done + 2 * s + 3)
    await core.dma(dir=STORE, mem_addr=C_BASE, mem_stride=4 * s, rows=m, buf_addr=0)
    await core.dma(dir=STORE, mem_addr=C_BASE + 1024, mem_stride=4 * s, rows=m, buf_addr=hi)

    def read(addr: int) -> np.ndarray:
        raw = bytes(core.mem.data[addr : addr + 4 * m * s])
        return np.frombuffer(raw, dtype="<i4").reshape(m, s)

    np.testing.assert_array_equal(read(C_BASE), golden.gemm(a[:m], w))
    want_hi = golden.gemm(a[m:], w) + golden.gemm(a[:m], w)
    np.testing.assert_array_equal(read(C_BASE + 1024), want_hi)
