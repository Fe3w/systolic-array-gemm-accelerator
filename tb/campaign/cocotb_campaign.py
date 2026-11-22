"""Verification campaign (M10): random compiler-driven GEMMs on sa_top, plus corners.

Per GEMM, from the seeded RNG: shape (M, N, K in 1 .. 4S + 3, biased to
non-multiples of S), tile order, m_c, memory read latency, max outstanding
reads and stall probability. Compile with sysarray.tile(), run on sa_top
through the memory model, compare C with golden.gemm, and compare the
counters with sysarray.predict(): exact when the memory cannot stall, a lower
bound otherwise. Every GEMM is recorded (pass/fail); the test fails at the end
if any GEMM failed, so one failure never hides the rest.

Environment: SYSARRAY_CAMPAIGN_N (default 20) GEMMs; SYSARRAY_LONG=1 also
runs the int32-wrap corner (K = 131072); SYSARRAY_RESULTS_DIR, when set,
receives one JSON line per GEMM (used by scripts/verify/campaign.py).
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


def _dim(rng, s: int) -> int:
    if rng.random() < 0.25:
        return s * rng.randint(1, 4)  # an exact multiple of S now and then
    return rng.randint(1, 4 * s + 3)


async def _run_one(dut, s: int, rng, a, b, order: str, m_c: int, mem_cfg: dict) -> dict:
    prog = tiler.tile(a, b, s=s, order=order, m_c=m_c)
    await reset_top(dut)
    size = max(1 << 16, prog.mem_size)
    top = Top(dut, make_memory(s, rng, size=size, **mem_cfg), s)
    for addr, data in prog.image:
        top.mem.data[addr : addr + len(data)] = data
    top.queue = list(prog.commands)
    await top.run_all(max_cycles=50_000_000)
    got = {k: _u(getattr(dut, k)) for k in ("cycles_total", "cycles_dma", "cycles_compute",
                                            "macs_issued")}  # fmt: skip
    pred = predict.predict(prog.commands, s=s, read_latency=mem_cfg["latency"])
    exact = mem_cfg["stalls"] == 0 and mem_cfg["max_outstanding"] > mem_cfg["latency"]
    c_ok = bool(np.array_equal(prog.read_c(top.mem.data), golden.gemm(a, b)))
    if exact:
        timing_ok = got == {"cycles_total": pred.cycles_total, "cycles_dma": pred.cycles_dma,
                            "cycles_compute": pred.cycles_compute,
                            "macs_issued": pred.macs_issued}  # fmt: skip
    else:
        timing_ok = (got["cycles_total"] >= pred.cycles_total
                     and got["macs_issued"] == pred.macs_issued)  # fmt: skip
    return {"M": a.shape[0], "N": b.shape[1], "K": a.shape[1], "order": order, "m_c": m_c,
            **mem_cfg, "err": _u(dut.err), "c_ok": c_ok, "timing_exact_check": exact,
            "timing_ok": timing_ok, "measured": got, "predicted_cycles_total": pred.cycles_total,
            "useful_macs": prog.stats.useful_macs, "n_commands": prog.stats.n_commands}  # fmt: skip


def _emit(records: list[dict], name: str) -> None:
    out = os.environ.get("SYSARRAY_RESULTS_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        with open(Path(out) / name, "a") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")


@cocotb.test()
async def test_campaign(dut) -> None:
    rng = get_rng("test_campaign")
    s = get_params()["S"]
    start_clock(dut.clk)
    n = int(os.environ.get("SYSARRAY_CAMPAIGN_N", "20"))
    records, t0 = [], time.time()
    for i in range(n):
        m, nn, k = _dim(rng, s), _dim(rng, s), _dim(rng, s)
        a = np.array([[rng.randint(-128, 127) for _ in range(k)] for _ in range(m)])
        b = np.array([[rng.randint(-128, 127) for _ in range(nn)] for _ in range(k)])
        order = rng.choice("AB")
        m_c = m if rng.random() < 0.5 else rng.randint(1, m)
        latency = rng.randint(1, 4)
        mem_cfg = {"latency": latency, "max_outstanding": rng.choice((1, 2, latency + 1, 8)),
                   "stalls": rng.choice((0.0, 0.0, 0.1, 0.3))}  # fmt: skip
        r = await _run_one(dut, s, rng, a, b, order, m_c, mem_cfg)
        r.update(index=i, S=s, seed=get_seed())
        records.append(r)
        if not (r["c_ok"] and r["timing_ok"] and r["err"] == 0):
            dut._log.error("GEMM %d FAILED: %s", i, r)
    _emit(records, f"campaign_S{s}.jsonl")
    bad = [r for r in records if not (r["c_ok"] and r["timing_ok"] and r["err"] == 0)]
    dut._log.info("campaign S=%d: %d GEMMs, %d failures, %d with exact timing check, %.1f s",
                  s, len(records), len(bad), sum(r["timing_exact_check"] for r in records),
                  time.time() - t0)  # fmt: skip
    assert not bad, f"{len(bad)} of {len(records)} GEMMs failed; first: {bad[0]}"


@cocotb.test()
async def test_corners(dut) -> None:
    """BRIEF §8 corners: all -128, all 127, mixed signs, M = N = K = 1, and (long) int32 wrap."""
    rng = get_rng("test_corners")
    s = get_params()["S"]
    start_clock(dut.clk)
    exact = {"latency": 2, "max_outstanding": 8, "stalls": 0.0}
    cases = [
        ("all -128", np.full((9, 2 * s + 1), -128), np.full((2 * s + 1, s + 3), -128)),
        ("all 127", np.full((7, 3 * s), 127), np.full((3 * s, 5), 127)),
        ("mixed signs", np.array([[(-1) ** (i + j) * 128 if (i + j) % 2 else 127
                                   for j in range(s + 1)] for i in range(5)]),
         np.array([[(-1) ** (i * j) * (100 + i) for j in range(s + 2)] for i in range(s + 1)])),
        ("M=N=K=1", np.array([[-128]]), np.array([[-128]])),
        ("M=1", np.full((1, 2 * s), 5), np.full((2 * s, 3 * s), -7)),
        ("N=1", np.full((3 * s, 2 * s), -3), np.full((2 * s, 1), 9)),
        ("K=1", np.full((4 * s, 1), 127), np.full((1, 2 * s), -128)),
    ]  # fmt: skip
    if os.environ.get("SYSARRAY_LONG", "0") not in ("", "0"):
        # C = 131072 * (-128) * (-128) = 2^31 -> wraps to -2^31 (D-004a), K multiple of S.
        cases.append(("int32 wrap K=131072", np.full((1, 131072), -128),
                      np.full((131072, s), -128)))  # fmt: skip
    records = []
    for name, a, b in cases:
        r = await _run_one(dut, s, rng, a, b, "A", a.shape[0], exact)
        r.update(corner=name, S=s, seed=get_seed())
        records.append(r)
        assert r["c_ok"] and r["timing_ok"] and r["err"] == 0, f"corner {name}: {r}"
        dut._log.info("corner %s: ok", name)
    if any(r.get("corner", "").startswith("int32 wrap") for r in records):
        assert golden.gemm(np.full((1, 131072), -128), np.full((131072, 1), -128))[0, 0] == -(2**31)
    _emit(records, f"corners_S{s}.jsonl")
