"""cocotb tests for rtl/top/sa_top.sv (sa_ctrl + sa_core), from docs/spec/ctrl.md §6.

Commands are encoded with sysarray.commands (the mirror of sa_pkg). A Python
functional model executes the same commands in program order (spec §1
semantics) on its own copy of memory; the final hardware memory must equal it.
The memory model (tb/common/memory.py) adds latency and random stalls.
"""

from __future__ import annotations

import cocotb
import numpy as np

from sysarray import funcsim, golden
from sysarray.commands import (
    ACCUMULATE,
    DEPTH,
    OP_COMPUTE,
    OP_LOAD_A,
    OP_LOAD_W,
    OP_STORE,
    OVERWRITE,
    Command,
)
from tb.common.top_harness import Top, _u, make_memory, reset_top
from tb.common.utils import get_params, get_rng, start_clock

IN_REGION = (0, 1 << 15)  # LOAD_W / LOAD_A read here
OUT_REGION = (1 << 15, 1 << 16)  # STORE writes here
OPS = (OP_LOAD_W, OP_LOAD_A, OP_COMPUTE, OP_STORE)


async def _setup(dut, rng, stalls: float, latency: int = 3) -> Top:
    p = get_params()
    start_clock(dut.clk)
    await reset_top(dut)
    return Top(dut, make_memory(p["S"], rng, stalls, latency), p["S"])


class Model:
    """The functional model (sysarray.funcsim) bound to its own copy of memory."""

    def __init__(self, s: int, mem: bytearray) -> None:
        self.mem = mem
        self.machine = funcsim.Machine(mem, s)

    def run(self, c: Command) -> None:
        self.machine.run(c)


def _fill_inputs(top: Top, rng) -> None:
    lo, hi = IN_REGION
    top.mem.data[lo:hi] = bytes(rng.getrandbits(8) for _ in range(hi - lo))


class Program:
    """Random valid command program (spec §1 constraints) with pair coverage."""

    def __init__(self, s: int, rng) -> None:
        self.s, self.rng = s, rng
        self.ibuf = [False] * DEPTH
        self.acc = [False] * DEPTH
        self.have_w = False
        self.cmds: list[Command] = []
        self.pairs: set[tuple[int, int]] = set()

    def _addr(self, region: tuple[int, int], rows: int, row_bytes: int) -> tuple[int, int]:
        stride = row_bytes * self.rng.randint(1, 3)
        lo, hi = region
        top = hi - ((rows - 1) * stride + row_bytes)
        return lo + self.s * self.rng.randint(0, (top - lo) // self.s), stride

    def _defined_run(self, flags: list[bool], cap: int) -> tuple[int, int] | None:
        starts = [i for i in range(DEPTH) if flags[i]]
        if not starts:
            return None
        b = self.rng.choice(starts)
        n = 1
        while n < cap and b + n < DEPTH and flags[b + n]:
            n += 1
        return b, self.rng.randint(1, n)

    def make(self, op: int) -> Command | None:
        s, rng = self.s, self.rng
        if op == OP_LOAD_W:
            addr, stride = self._addr(IN_REGION, s, s)
            self.have_w = True
            rows = rng.choice((0, 0, s, rng.randint(1, s)))  # 0 or S: full; else partial (M11b)
            return Command(op=op, mem_addr=addr, mem_stride=stride, rows=rows)
        if op == OP_LOAD_A:
            rows = rng.randint(1, 20)
            b = rng.randint(0, DEPTH - rows)
            addr, stride = self._addr(IN_REGION, rows, s)
            for i in range(rows):
                self.ibuf[b + i] = True
            return Command(op=op, mem_addr=addr, mem_stride=stride, rows=rows, buf_addr=b)
        if op == OP_COMPUTE:
            run = self._defined_run(self.ibuf, 20)
            if not self.have_w or run is None:
                return None
            b, rows = run
            mode = OVERWRITE
            acc = rng.randint(0, DEPTH - rows)
            if rng.random() < 0.5:  # accumulate onto a defined acc run if one exists
                acc_run = self._defined_run(self.acc, rows)
                if acc_run is not None and acc_run[1] == rows:
                    acc, mode = acc_run[0], ACCUMULATE
            for i in range(rows):
                self.acc[acc + i] = True
            return Command(op=op, acc_mode=mode, rows=rows, buf_addr=b, acc_addr=acc)
        run = self._defined_run(self.acc, 12)
        if run is None:
            return None
        b, rows = run
        addr, stride = self._addr(OUT_REGION, rows, 4 * s)
        return Command(op=OP_STORE, mem_addr=addr, mem_stride=stride, rows=rows, buf_addr=b)

    def build(self, n_min: int) -> list[Command]:
        for op in (OP_LOAD_W, OP_LOAD_A, OP_COMPUTE, OP_STORE):  # make every op possible
            self.cmds.append(self.make(op))
        while len(self.cmds) < n_min or len(self.pairs) < 16:
            prev = self.cmds[-1].op
            unseen = [op for op in OPS if (prev, op) not in self.pairs]
            order = unseen + [op for op in OPS if op not in unseen]
            if self.rng.random() < 0.3:
                self.rng.shuffle(order)
            for op in order:
                c = self.make(op)
                if c is not None:
                    self.pairs.add((prev, op))
                    self.cmds.append(c)
                    break
        return self.cmds


@cocotb.test()
async def test_random_programs(dut) -> None:
    """Random valid programs covering all 16 ordered command pairs (§6 test 1, test 4)."""
    rng = get_rng("test_random_programs")
    top = await _setup(dut, rng, stalls=0.2)
    s = top.s
    _fill_inputs(top, rng)
    model = Model(s, bytearray(top.mem.data))
    prog = Program(s, rng)
    cmds = prog.build(n_min=120)
    assert len(prog.pairs) == 16
    for c in cmds:
        model.run(c)
    top.queue = list(cmds)
    await top.run_all()
    assert _u(dut.err) == 0, f"unexpected error code {_u(dut.err_code)}"
    assert bytes(top.mem.data) == bytes(model.mem), "memory differs from the functional model"
    # Counters (spec §4)
    macs = s * s * sum(c.rows for c in cmds if c.op == OP_COMPUTE)
    assert _u(dut.macs_issued) == macs
    assert _u(dut.cycles_dma) == top.dma_busy_cycles
    assert _u(dut.cycles_compute) == top.feed_busy_cycles
    assert _u(dut.cycles_total) == top.last_store_done - top.first_accept + 1
    dut._log.info("%d commands, all 16 pairs, %d cycles total, memory matches the model",
                  len(cmds), _u(dut.cycles_total))  # fmt: skip


@cocotb.test()
async def test_gemm_program(dut) -> None:
    """A GEMM (M=13, K=2S, N=2S) written as commands; C equals golden.gemm (§6 test 2)."""
    rng = get_rng("test_gemm_program")
    top = await _setup(dut, rng, stalls=0.2)
    s = top.s
    m, k, n = 13, 2 * s, 2 * s
    a = np.array([[rng.randint(-128, 127) for _ in range(k)] for _ in range(m)])
    b = np.array([[rng.randint(-128, 127) for _ in range(n)] for _ in range(k)])
    a_base, b_base, c_base = 0x0000, 0x2000, 0x8000
    top.mem.data[a_base : a_base + m * k] = a.astype(np.int8).tobytes()
    top.mem.data[b_base : b_base + k * n] = b.astype(np.int8).tobytes()
    for n0 in range(0, n, s):
        for kt, k0 in enumerate(range(0, k, s)):
            top.queue += [
                Command(op=OP_LOAD_W, mem_addr=b_base + k0 * n + n0, mem_stride=n),
                Command(op=OP_LOAD_A, mem_addr=a_base + k0, mem_stride=k, rows=m),
                Command(op=OP_COMPUTE, acc_mode=ACCUMULATE if kt else OVERWRITE, rows=m),
            ]
        top.queue.append(Command(op=OP_STORE, mem_addr=c_base + 4 * n0, mem_stride=4 * n,
                                 rows=m))  # fmt: skip
    await top.run_all()
    c = np.frombuffer(bytes(top.mem.data[c_base : c_base + 4 * m * n]), dtype="<i4").reshape(m, n)
    assert np.array_equal(c, golden.gemm(a, b)), "C != golden"


@cocotb.test()
async def test_errors(dut) -> None:
    """Each error code: flagged, command dropped, no hang, err_clear, next runs (§6 test 3)."""
    rng = get_rng("test_errors")
    top = await _setup(dut, rng, stalls=0.0)
    s = top.s
    _fill_inputs(top, rng)
    model = Model(s, bytearray(top.mem.data))
    bad = [
        (Command(op=OP_COMPUTE, rows=4), 4),  # before any LOAD_W
        (Command(op=5, rows=4), 1),
        (Command(op=OP_LOAD_A, rows=0), 2),
        (Command(op=OP_LOAD_A, rows=300), 2),
        (Command(op=OP_LOAD_A, rows=10, buf_addr=250), 3),
        (Command(op=OP_STORE, rows=8, buf_addr=252), 3),
        (Command(op=OP_COMPUTE, rows=10, buf_addr=0, acc_addr=250), 3),
        (Command(op=7, rows=0), 1),  # opcode error wins over rows error
    ]
    good = [
        Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
        Command(op=OP_LOAD_A, mem_addr=64, mem_stride=s, rows=4),
        Command(op=OP_COMPUTE, rows=4),
        Command(op=OP_STORE, mem_addr=OUT_REGION[0], mem_stride=4 * s, rows=4),
    ]
    for i, (cmd, code) in enumerate(bad):
        top.queue = [cmd]
        await top.run_all(max_cycles=200)
        err, got = _u(dut.err), _u(dut.err_code)
        assert err == 1 and got == code, f"bad command {i}: err={err} code={got}, want {code}"
        await top.tick(err_clear=1)
        await top.tick()
        assert _u(dut.err) == 0, "err_clear did not clear"
        if i == 0:  # after the no-weights error, run a good program once
            for c in good:
                model.run(c)
            top.queue = list(good)
            await top.run_all()
            assert _u(dut.err) == 0
    assert bytes(top.mem.data) == bytes(model.mem), "a dropped command changed memory"


@cocotb.test()
async def test_cycle_table(dut) -> None:
    """Each command alone with an always-ready memory, L = 3 (§6 test 5, spec §3)."""
    rng = get_rng("test_cycle_table")
    top = await _setup(dut, rng, stalls=0.0, latency=3)
    s, lat = top.s, 3
    _fill_inputs(top, rng)
    r = 5
    d_w = 3 + s + lat  # LOAD_W: DMA done (S rows), then the feeder starts one cycle later
    # M11c (D-028): CHECK takes two cycles (t + 1, t + 2), so a unit starts at t + 3
    # and cmd_ready returns one cycle after the start; LOAD_W holds the dispatcher
    # until its feeder start.
    cases = [
        (
            Command(op=OP_LOAD_A, mem_addr=0, mem_stride=s, rows=r),
            [(3, "dma_start"), (3 + r + lat, "dma_done")],
            4,
        ),
        (
            Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
            [(3, "dma_start"), (d_w, "dma_done"), (d_w + 1, "f_start"), (d_w + s + 3, "f_done")],
            d_w + 2,
        ),
        (Command(op=OP_COMPUTE, rows=r), [(3, "f_start"), (r + 5, "f_done")], 4),
        (
            Command(op=OP_STORE, mem_addr=OUT_REGION[0], mem_stride=4 * s, rows=r),
            [(3, "dma_start"), (3 + 4 * r + 1, "dma_done")],
            4,
        ),
    ]
    for cmd, expect, ready_at in cases:
        for _ in range(4 * s):  # let any previous drain rule expire
            await top.tick()
        top.events.clear()
        top.queue = [cmd]
        t = None
        back = None
        for _ in range(400):
            st = await top.tick()
            if t is None and top.accepted and top.accepted[-1][1] is cmd:
                t = top.accepted[-1][0]
            if t is not None and st["cycle"] > t and st["ready"] and back is None:
                back = st["cycle"] - t
            if back is not None and not st["busy"]:
                break
        got = sorted((c - t, e) for c, e in top.events)
        assert got == sorted(expect), f"op {cmd.op}: events {got}, expected {sorted(expect)}"
        assert back == ready_at, f"op {cmd.op}: cmd_ready back at t+{back}, expected t+{ready_at}"


@cocotb.test()
async def test_back_to_back_compute(dut) -> None:
    """COMPUTE directly after COMPUTE (different rows, modes and accumulator bases).

    Regression for the accumulator configuration hazard found in M8: the second
    COMPUTE must not change the accumulator's base/mode while the first one's
    outputs are still arriving (docs/spec/acc.md §2 rule 3).
    """
    rng = get_rng("test_back_to_back_compute")
    top = await _setup(dut, rng, stalls=0.0)
    s = top.s
    _fill_inputs(top, rng)
    model = Model(s, bytearray(top.mem.data))
    out = OUT_REGION[0]
    cmds = [
        Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
        Command(op=OP_LOAD_A, mem_addr=256, mem_stride=s, rows=6),
        Command(op=OP_COMPUTE, rows=3, buf_addr=0, acc_addr=10),
        Command(op=OP_COMPUTE, rows=1, buf_addr=3, acc_addr=100),
        Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=3, buf_addr=3, acc_addr=10),
        Command(op=OP_STORE, mem_addr=out, mem_stride=4 * s, rows=3, buf_addr=10),
        Command(op=OP_STORE, mem_addr=out + 1024, mem_stride=4 * s, rows=1, buf_addr=100),
    ]
    for c in cmds:
        model.run(c)
    top.queue = list(cmds)
    await top.run_all()
    assert bytes(top.mem.data) == bytes(model.mem), "back-to-back COMPUTE corrupted results"


@cocotb.test()
async def test_unwritten_rows_error(dut) -> None:
    """Error 5: COMPUTE on never-loaded input rows, ACCUMULATE into or STORE of
    never-written accumulator rows (docs/spec/ctrl.md §1, M11b issue 12)."""
    rng = get_rng("test_unwritten_rows_error")
    top = await _setup(dut, rng, stalls=0.0)
    s = top.s
    _fill_inputs(top, rng)
    model = Model(s, bytearray(top.mem.data))
    good = [
        Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
        Command(op=OP_LOAD_A, mem_addr=64, mem_stride=s, rows=4, buf_addr=10),
        Command(op=OP_COMPUTE, rows=4, buf_addr=10, acc_addr=20),
    ]
    for c in good:
        model.run(c)
    top.queue = list(good)
    await top.run_all()
    assert _u(dut.err) == 0
    bad = [
        Command(op=OP_COMPUTE, rows=4, buf_addr=11, acc_addr=0),  # ibuf row 14 never loaded
        Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=4, buf_addr=10, acc_addr=21),  # acc 24
        Command(op=OP_STORE, mem_addr=OUT_REGION[0], mem_stride=4 * s, rows=5, buf_addr=20),
    ]
    for i, cmd in enumerate(bad):
        top.queue = [cmd]
        await top.run_all(max_cycles=200)
        err, got = _u(dut.err), _u(dut.err_code)
        assert err == 1 and got == 5, f"bad command {i}: err={err} code={got}, want 5"
        await top.tick(err_clear=1)
        await top.tick()
    ok = Command(op=OP_STORE, mem_addr=OUT_REGION[0], mem_stride=4 * s, rows=4, buf_addr=20)
    model.run(ok)
    top.queue = [ok]
    await top.run_all()
    assert _u(dut.err) == 0
    assert bytes(top.mem.data) == bytes(model.mem)


@cocotb.test()
async def test_counter_width(dut) -> None:
    """Performance counters are 48 bits wide (M11b issue 13)."""
    for name in ("cycles_total", "cycles_dma", "cycles_compute", "macs_issued"):
        assert len(getattr(dut, name)) == 48, f"{name} is {len(getattr(dut, name))} bits"


async def _run_and_compare(top: Top, model: Model, cmds: list[Command], label: str) -> None:
    for c in cmds:
        model.run(c)
    top.queue = list(cmds)
    await top.run_all()
    assert _u(top.dut.err) == 0, f"{label}: err_code {_u(top.dut.err_code)}"
    assert bytes(top.mem.data) == bytes(model.mem), f"{label}: memory differs from the model"


@cocotb.test()
async def test_overlap(dut) -> None:
    """M13: a LOAD_A into the other input-buffer half runs while a COMPUTE streams."""
    rng = get_rng("test_overlap")
    top = await _setup(dut, rng, stalls=0.0)
    s = top.s
    _fill_inputs(top, rng)
    model = Model(s, bytearray(top.mem.data))
    r, half, out = 40, DEPTH // 2, OUT_REGION[0]
    cmds = [
        Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
        Command(op=OP_LOAD_A, mem_addr=512, mem_stride=s, rows=r, buf_addr=0),
        Command(op=OP_COMPUTE, rows=r, buf_addr=0, acc_addr=0),
        Command(op=OP_LOAD_A, mem_addr=4096, mem_stride=s, rows=r, buf_addr=half),
        Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=r, buf_addr=half, acc_addr=0),
        Command(op=OP_STORE, mem_addr=out, mem_stride=4 * s, rows=r, buf_addr=0),
    ]
    await _run_and_compare(top, model, cmds, "overlap")
    starts = [c for c, e in top.events if e == "dma_start"]
    f_done = [c for c, e in top.events if e == "f_done"]
    # dma_start #3 is the second LOAD_A; f_done #2 is the first COMPUTE's.
    assert starts[2] < f_done[1], f"LOAD_A at {starts[2]} did not overlap COMPUTE ({f_done[1]})"


@cocotb.test()
async def test_hazards(dut) -> None:
    """M13: every dependency the controller must respect, with memory stalls.

    RAW LOAD_A -> COMPUTE, WAR COMPUTE -> LOAD_A (same rows, new data), LOAD_W
    while the previous weights are still streaming, STORE after COMPUTE, and an
    OVERWRITE COMPUTE into rows a STORE is still reading.
    """
    rng = get_rng("test_hazards")
    for stalls in (0.0, 0.3):
        top = await _setup(dut, rng, stalls=stalls)
        s = top.s
        _fill_inputs(top, rng)
        model = Model(s, bytearray(top.mem.data))
        out = OUT_REGION[0]
        cmds = [
            Command(op=OP_LOAD_W, mem_addr=0, mem_stride=s),
            Command(op=OP_LOAD_A, mem_addr=256, mem_stride=s, rows=20, buf_addr=0),
            Command(op=OP_COMPUTE, rows=20, buf_addr=0, acc_addr=0),          # RAW on rows 0..19
            Command(op=OP_LOAD_A, mem_addr=2048, mem_stride=s, rows=20, buf_addr=5),  # WAR
            Command(op=OP_LOAD_W, mem_addr=64, mem_stride=s),                   # weights in use
            Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=20, buf_addr=5, acc_addr=0),
            Command(op=OP_STORE, mem_addr=out, mem_stride=4 * s, rows=20, buf_addr=0),
            Command(op=OP_COMPUTE, rows=20, buf_addr=0, acc_addr=0),          # WAR on acc rows
            Command(op=OP_LOAD_W, mem_addr=128, mem_stride=s, rows=3),
            Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=7, buf_addr=10, acc_addr=4),
            Command(op=OP_STORE, mem_addr=out + 2048, mem_stride=4 * s, rows=20, buf_addr=0),
        ]
        await _run_and_compare(top, model, cmds, f"hazards stalls={stalls}")
