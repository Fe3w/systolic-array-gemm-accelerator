"""Latency / per-tile cycle measurement for sa_array (M4), driven by scripts/measure/latency.py.

For one array size S (from the build parameters) and each M in MS, one tile is
run from an idle array: S weight-load cycles, then M valid rows back to back,
then a drain. Every output row is checked against golden.gemm and its exact
cycle (spec §4) by the same reference model as tb/array/cocotb_array.py, and
two numbers are measured from the observed c_valid trace:

  latency_first = (first cycle with c_valid = 1) - (first cycle with a_valid = 1)
  t_tile        = (last cycle with c_valid = 1) + 1 - (first cycle with w_load = 1)

Rows are appended to $SYSARRAY_RESULTS_DIR/latency_S<S>.csv. This module only
measures; the predictions and the comparison live in the script.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import cocotb

from tb.array.cocotb_array import DEFAULTS, OUTPUTS, Sched, _check, _rand_matrix, _setup
from tb.common.utils import drive_cycles, get_rng, get_seed

MS = (1, 2, 8, 13, 64)


@cocotb.test()
async def measure_latency(dut) -> None:
    out_dir = Path(os.environ["SYSARRAY_RESULTS_DIR"])
    rng = get_rng("measure_latency")
    s = await _setup(dut)
    rows = []
    for m in MS:
        sched = Sched(s)
        sched.load(_rand_matrix(rng, s, s))
        for row in _rand_matrix(rng, m, s):
            sched.row(row.tolist())
        sched.drain()
        observed = await drive_cycles(dut, sched.stim, OUTPUTS, DEFAULTS)
        _check(observed, sched.expected, s, f"measure S={s} M={m}")

        first_load = next(k for k, st in enumerate(sched.stim) if st.get("w_load") == 1)
        first_valid = next(k for k, st in enumerate(sched.stim) if st.get("a_valid") == 1)
        c_cycles = [k for k, o in enumerate(observed) if o["c_valid"] == 1]
        rows.append(
            {
                "S": s,
                "M": m,
                "latency_first": c_cycles[0] - first_valid,
                "t_tile": c_cycles[-1] + 1 - first_load,
                "seed": get_seed(),
            }
        )
        dut._log.info("S=%d M=%d: %s", s, m, rows[-1])

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"latency_S{s}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
