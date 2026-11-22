"""Compiler-driven GEMMs on sa_top (M9): sysarray.tile() -> commands -> RTL -> C vs golden.

With an always-ready memory (no stalls, L = 3, enough outstanding reads) the
controller has no data-dependent stalls, so the hardware counters must equal
sysarray.predict() exactly. With random stalls, C must still be exact and the
measured cycles can only be larger than predicted.
"""

from __future__ import annotations

import os

import cocotb
import numpy as np

from sysarray import golden, predict, tiler
from tb.common.top_harness import Top, _u, make_memory, reset_top
from tb.common.utils import get_params, get_rng, start_clock

LATENCY = 3


def _shape(rng, s: int) -> tuple[int, int, int]:
    return tuple(rng.randint(1, 3 * s + 1) for _ in range(3))  # type: ignore[return-value]


async def _run_program(dut, top: Top, prog: tiler.Program) -> dict[str, int]:
    for addr, data in prog.image:
        top.mem.data[addr : addr + len(data)] = data
    top.queue = list(prog.commands)
    await top.run_all()
    assert _u(dut.err) == 0, f"controller error {_u(dut.err_code)}"
    return {k: _u(getattr(dut, k)) for k in ("cycles_total", "cycles_dma", "cycles_compute",
                                             "macs_issued")}  # fmt: skip


@cocotb.test()
async def test_compiled_exact_timing(dut) -> None:
    """Random shapes, both orders, always-ready memory: C exact and counters == predict()."""
    rng = get_rng("test_compiled_exact_timing")
    s = get_params()["S"]
    start_clock(dut.clk)
    n = int(os.environ.get("SYSARRAY_GEMM_N", "6"))
    for i in range(n):
        m, nn, k = _shape(rng, s)
        order = rng.choice("AB")
        a = np.array([[rng.randint(-128, 127) for _ in range(k)] for _ in range(m)])
        b = np.array([[rng.randint(-128, 127) for _ in range(nn)] for _ in range(k)])
        prog = tiler.tile(a, b, s=s, order=order)
        await reset_top(dut)  # counters start from zero for each program
        top = Top(dut, make_memory(s, rng, stalls=0.0, latency=LATENCY, max_outstanding=8), s)
        got = await _run_program(dut, top, prog)
        np.testing.assert_array_equal(prog.read_c(top.mem.data), golden.gemm(a, b))
        pred = predict.predict(prog.commands, s=s, read_latency=LATENCY)
        want = {"cycles_total": pred.cycles_total, "cycles_dma": pred.cycles_dma,
                "cycles_compute": pred.cycles_compute, "macs_issued": pred.macs_issued}  # fmt: skip
        assert (
            got == want
        ), f"#{i} M={m} N={nn} K={k} order {order}: measured {got}, predicted {want}"
        dut._log.info("#%d M=%d N=%d K=%d order %s: C ok, cycles_total %d == predicted",
                      i, m, nn, k, order, got["cycles_total"])  # fmt: skip


@cocotb.test()
async def test_compiled_with_stalls(dut) -> None:
    """Random shapes with memory stalls: C exact, measured cycles >= predicted."""
    rng = get_rng("test_compiled_with_stalls")
    s = get_params()["S"]
    start_clock(dut.clk)
    for _ in range(4):
        m, nn, k = _shape(rng, s)
        order = rng.choice("AB")
        a = np.array([[rng.randint(-128, 127) for _ in range(k)] for _ in range(m)])
        b = np.array([[rng.randint(-128, 127) for _ in range(nn)] for _ in range(k)])
        prog = tiler.tile(a, b, s=s, order=order, m_c=rng.randint(1, m))
        await reset_top(dut)
        top = Top(dut, make_memory(s, rng, stalls=0.25, latency=LATENCY), s)
        got = await _run_program(dut, top, prog)
        np.testing.assert_array_equal(prog.read_c(top.mem.data), golden.gemm(a, b))
        pred = predict.predict(prog.commands, s=s, read_latency=LATENCY)
        assert got["cycles_total"] >= pred.cycles_total
        assert got["macs_issued"] == pred.macs_issued
