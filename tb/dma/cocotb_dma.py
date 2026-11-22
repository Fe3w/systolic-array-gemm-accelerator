"""cocotb tests for rtl/dma/sa_dma.sv via sa_dma_top, from docs/spec/dma.md §4 and §6.

Each cycle (falling edge): read the DMA's registered request valids/payloads,
step the Python memory model (tb/common/memory.py), drive the memory's outputs
and the testbench's descriptor inputs, wait 1 ns, then sample busy/done/
start_dropped (done may depend combinationally on rd_resp_valid). A protocol
checker runs every cycle (§6 test 4).
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import FallingEdge, Timer

from tb.common.memory import Memory
from tb.common.utils import get_params, get_rng, reset_sync, start_clock

LOAD, STORE = 0, 1
WBUF, IBUF = 0, 1
TB_DEFAULTS = {
    "start": 0,
    "dir": 0,
    "target": 0,
    "mem_addr": 0,
    "mem_stride": 0,
    "rows": 0,
    "buf_addr": 0,
    "wb_re": 0,
    "wb_raddr": 0,
    "ib_re": 0,
    "ib_raddr": 0,
    "src_we": 0,
    "src_waddr": 0,
    "src_wdata": 0,
}
MEM_SIZE = 1 << 16


def _u(sig) -> int:
    v = sig.value
    return int(v) if not hasattr(v, "to_unsigned") else v.to_unsigned()


class Tb:
    def __init__(self, dut, mem: Memory) -> None:
        self.dut, self.mem = dut, mem
        self.cycle = 0
        self.prev: dict[str, tuple] = {}
        self.violations: list[str] = []

    def _protocol(self, name: str, valid: int, payload: tuple, ready: int, busy: int) -> None:
        prev = self.prev.get(name)
        if prev is not None:
            p_valid, p_payload, p_ready = prev
            if p_valid and not p_ready and (not valid or payload != p_payload):
                self.violations.append(f"cycle {self.cycle}: {name} dropped/changed while stalled")
        if valid and not busy:
            self.violations.append(f"cycle {self.cycle}: {name} valid outside a command")
        self.prev[name] = (valid, payload, ready)

    async def tick(self, **inputs: int) -> dict[str, int]:
        dut = self.dut
        await FallingEdge(dut.clk)
        rd_v, rd_a = _u(dut.rd_req_valid), _u(dut.rd_req_addr)
        wr_v, wr_a, wr_d = _u(dut.wr_req_valid), _u(dut.wr_req_addr), _u(dut.wr_req_data)
        busy_before = _u(dut.busy)
        out = self.mem.step(
            {
                "rd_req_valid": rd_v,
                "rd_req_addr": rd_a,
                "rd_resp_ready": _u(dut.rd_resp_ready),
                "wr_req_valid": wr_v,
                "wr_req_addr": wr_a,
                "wr_req_data": wr_d,
            }
        )
        for name, value in {**TB_DEFAULTS, **inputs, **out}.items():
            getattr(dut, name).value = value
        self._protocol("rd_req", rd_v, (rd_a,), out["rd_req_ready"], busy_before)
        self._protocol("wr_req", wr_v, (wr_a, wr_d), out["wr_req_ready"], busy_before)
        await Timer(1, unit="ns")
        sample = {n: _u(getattr(dut, n)) for n in ("busy", "done", "start_dropped")}
        sample["cycle"] = self.cycle
        self.cycle += 1
        return sample

    async def run_desc(self, max_cycles: int = 20000, **desc: int) -> tuple[int, int]:
        """Start a descriptor; return (start cycle, done cycle)."""
        t = (await self.tick(start=1, **desc))["cycle"]
        for _ in range(max_cycles):
            s = await self.tick()
            if s["done"]:
                assert not self.violations, f"protocol: {self.violations[:3]}"
                return t, s["cycle"]
        raise AssertionError(f"descriptor {desc} did not finish in {max_cycles} cycles")

    async def read_buffer(self, target: int, addr: int) -> int:
        re, ra, rd = (
            ("wb_re", "wb_raddr", "wb_rdata")
            if target == WBUF
            else ("ib_re", "ib_raddr", "ib_rdata")
        )
        await self.tick(**{re: 1, ra: addr})
        await self.tick()
        return _u(getattr(self.dut, rd))

    async def write_source(self, rows: list[int], base: int = 0) -> None:
        for i, row in enumerate(rows):
            await self.tick(src_we=1, src_waddr=base + i, src_wdata=row)


async def _setup(dut) -> dict[str, int]:
    """Clock, idle inputs and reset, once per cocotb test."""
    p = get_params()
    start_clock(dut.clk)
    for name, value in TB_DEFAULTS.items():
        getattr(dut, name).value = value
    for name in ("rd_req_ready", "rd_resp_valid", "rd_resp_data", "wr_req_ready"):
        getattr(dut, name).value = 0
    await reset_sync(dut.clk, dut.rst, cycles=2)
    return p


def _mem(
    p: dict[str, int], rng: random.Random, latency: int = 1, stalls: float = 0.0, mo: int = 64
):
    return Memory(
        size=MEM_SIZE,
        beat_bytes=p["S"],
        read_latency=latency,
        max_outstanding=mo,
        rng=random.Random(rng.getrandbits(32)),
        req_stall=stalls,
        resp_stall=stalls,
        wr_stall=stalls,
    )


async def _load_and_check(tb: Tb, p, rng, target: int, rows: int) -> tuple[int, int]:
    s = p["S"]
    depth = s if target == WBUF else p["IN_DEPTH"]
    rows = min(rows, depth)
    stride = s * rng.randint(1, 4)
    base_addr = s * rng.randint(0, 64)
    buf_addr = rng.randint(0, depth - rows)
    expect = []
    for i in range(rows):
        beat = rng.getrandbits(8 * s)
        tb.mem.write_beat(base_addr + i * stride, beat)
        expect.append(beat)
    t, d = await tb.run_desc(
        dir=LOAD, target=target, mem_addr=base_addr, mem_stride=stride, rows=rows, buf_addr=buf_addr
    )
    for i, beat in enumerate(expect):
        got = await tb.read_buffer(target, buf_addr + i)
        assert got == beat, f"LOAD target {target} row {i}: {got:#x} != {beat:#x}"
    return t, d


async def _store_and_check(tb: Tb, p, rng, rows: int) -> tuple[int, int]:
    s, acc_bits = p["S"], p["S"] * 32
    rows = min(rows, p["ACC_DEPTH"])
    src = [rng.getrandbits(acc_bits) for _ in range(rows)]
    base = rng.randint(0, p["ACC_DEPTH"] - rows)
    await tb.write_source(src, base)
    stride = 4 * s * rng.randint(1, 3)
    mem_addr = s * rng.randint(0, 64)
    t, d = await tb.run_desc(
        dir=STORE, mem_addr=mem_addr, mem_stride=stride, rows=rows, buf_addr=base
    )
    for i, row in enumerate(src):
        a = mem_addr + i * stride
        got = int.from_bytes(tb.mem.data[a : a + 4 * s], "little")
        assert got == row, f"STORE row {i}: {got:#x} != {row:#x}"
    return t, d


@cocotb.test()
async def test_load_timing_always_ready(dut) -> None:
    """LOAD done in cycle t + R + L with an always-ready memory, L in {1, 3} (§6 test 1)."""
    rng = get_rng("test_load_timing_always_ready")
    p = await _setup(dut)
    for latency in (1, 3):
        tb = Tb(dut, Memory(MEM_SIZE, p["S"], read_latency=latency))
        for target, rows in ((WBUF, p["S"]), (IBUF, 1), (IBUF, 17), (IBUF, p["IN_DEPTH"])):
            t, d = await _load_and_check(tb, p, rng, target, rows)
            r = min(rows, p["S"] if target == WBUF else p["IN_DEPTH"])
            assert d == t + r + latency, f"L={latency} R={r}: done at t+{d - t}"
        assert not tb.violations, tb.violations[:5]


@cocotb.test()
async def test_store_timing_always_ready(dut) -> None:
    """STORE done in cycle t + 4R + 1 with an always-ready memory (§6 test 2)."""
    rng = get_rng("test_store_timing_always_ready")
    p = await _setup(dut)
    tb = Tb(dut, Memory(MEM_SIZE, p["S"], read_latency=1))
    for rows in (1, 2, 9, p["ACC_DEPTH"]):
        t, d = await _store_and_check(tb, p, rng, rows)
        r = min(rows, p["ACC_DEPTH"])
        assert d == t + 4 * r + 1, f"STORE R={r}: done at t+{d - t}"
    assert not tb.violations, tb.violations[:5]


@cocotb.test()
async def test_random_with_stalls(dut) -> None:
    """Random LOADs and STOREs with stalls on every channel (§6 tests 3-4)."""
    rng = get_rng("test_random_with_stalls")
    p = await _setup(dut)
    for mo, latency in ((1, 2), (4, 3)):
        tb = Tb(dut, _mem(p, rng, latency=latency, stalls=0.3, mo=mo))
        for _ in range(12):
            if rng.random() < 0.5:
                target = rng.choice((WBUF, IBUF))
                await _load_and_check(tb, p, rng, target, rng.randint(1, 40))
            else:
                await _store_and_check(tb, p, rng, rng.randint(1, 12))
        assert not tb.violations, tb.violations[:5]
        dut._log.info(
            "stalls mo=%d L=%d: %d reads, %d writes, 0 violations",
            mo,
            latency,
            tb.mem.reads,
            tb.mem.writes,
        )


@cocotb.test()
async def test_zero_rows_and_start_while_busy(dut) -> None:
    """rows = 0 finishes in t + 1; start while busy is ignored with start_dropped (§6 test 5)."""
    rng = get_rng("test_zero_rows_and_start_while_busy")
    p = await _setup(dut)
    tb = Tb(dut, Memory(MEM_SIZE, p["S"], read_latency=2))
    for direction in (LOAD, STORE):
        t, d = await tb.run_desc(dir=direction, target=IBUF, rows=0)
        assert d == t + 1, f"rows=0 dir={direction}: done at t+{d - t}"
    # start a 20-row LOAD, then poke start twice while it runs
    rows = 20
    for i in range(rows):
        tb.mem.write_beat(i * p["S"], rng.getrandbits(8 * p["S"]))
    t = (await tb.tick(start=1, dir=LOAD, target=IBUF, mem_stride=p["S"], rows=rows))["cycle"]
    s1 = await tb.tick(start=1, dir=STORE, rows=5)  # cycle t+1: busy -> dropped
    s2 = await tb.tick()
    assert s1["start_dropped"] == 0 and s2["start_dropped"] == 1, (s1, s2)
    done = None
    for _ in range(200):
        s = await tb.tick()
        if s["done"]:
            done = s["cycle"]
            break
    assert done == t + rows + 2, f"LOAD with dropped start: done at t+{done - t}"
    assert tb.mem.writes == 0, "dropped STORE must not write memory"
    assert not tb.violations, tb.violations[:5]
