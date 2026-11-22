"""Benchmark runner for M11: compiled GEMMs on sa_top, counters recorded per run.

Shapes come from $SYSARRAY_PERF_SHAPES (JSON list of {shape_id, M, N, K, order,
m_c}); results go to $SYSARRAY_RESULTS_DIR/perf.jsonl. Memory: always ready,
read latency 3, one request per cycle (the predictor's assumption), so the
measured counters can be compared with sysarray.predict() directly. Operands
are random int8 (values do not change the cycle count); C is checked against
golden.gemm for every run.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import cocotb
import numpy as np

from sysarray import golden, predict, tiler
from tb.common.top_harness import Top, _u, make_memory, reset_top
from tb.common.utils import get_params, get_rng, get_seed, start_clock

LATENCY = 3


@cocotb.test()
async def run_benchmarks(dut) -> None:
    rng = get_rng("run_benchmarks")
    s = get_params()["S"]
    start_clock(dut.clk)
    shapes = json.loads(os.environ["SYSARRAY_PERF_SHAPES"])
    out = Path(os.environ["SYSARRAY_RESULTS_DIR"]) / "perf.jsonl"
    nrng = np.random.default_rng(get_seed())
    for sh in shapes:
        t0 = time.time()
        m, n, k = sh["M"], sh["N"], sh["K"]
        a = nrng.integers(-128, 128, size=(m, k))
        b = nrng.integers(-128, 128, size=(k, n))
        prog = tiler.tile(a, b, s=s, order=sh["order"], m_c=sh.get("m_c"))
        await reset_top(dut)
        mem = make_memory(s, rng, stalls=0.0, latency=LATENCY, max_outstanding=8,
                          size=max(1 << 16, prog.mem_size))  # fmt: skip
        top = Top(dut, mem, s)
        for addr, data in prog.image:
            mem.data[addr : addr + len(data)] = data
        top.queue = list(prog.commands)
        await top.run_all(max_cycles=200_000_000)
        assert _u(dut.err) == 0
        c_ok = bool(np.array_equal(prog.read_c(mem.data), golden.gemm(a, b)))
        pred = predict.predict(prog.commands, s=s, read_latency=LATENCY,
                               useful_macs=prog.stats.useful_macs)  # fmt: skip
        rec = {**sh, "S": s, "m_c": prog.stats.m_c, "c_ok": c_ok,
               **{c: _u(getattr(dut, c)) for c in ("cycles_total", "cycles_dma",
                                                   "cycles_compute", "macs_issued")},
               "useful_macs": prog.stats.useful_macs, "predicted_cycles": pred.cycles_total,
               "weight_bytes": prog.stats.weight_bytes, "act_bytes": prog.stats.act_bytes,
               "out_bytes": prog.stats.out_bytes, "n_commands": prog.stats.n_commands,
               "seed": get_seed(), "wall_s": round(time.time() - t0, 1)}  # fmt: skip
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        dut._log.info("%s %s m_c=%d: cycles %d (predicted %d), C ok=%s, %.0f s", sh["shape_id"],
                      sh["order"], rec["m_c"], rec["cycles_total"], pred.cycles_total, c_ok,
                      rec["wall_s"])  # fmt: skip
        assert c_ok, f"{sh}: C != golden"
