"""pytest launcher for the end-to-end sa_core tests (tb/core/cocotb_core.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

SOURCES = (
    "common/sa_reg.sv",
    "pe/sa_pe.sv",
    "array/sa_grid.sv",
    "array/sa_array.sv",
    "mem/sa_sram.sv",
    "mem/sa_acc.sv",
    "array/sa_feeder.sv",
    "dma/sa_dma.sv",
    "core/sa_core.sv",
)
CONFIGS = [(4, 64, 64), (8, 256, 256)]  # (S, IN_DEPTH, ACC_DEPTH)


@pytest.mark.parametrize(("s", "ind", "accd"), CONFIGS, ids=[f"S{c[0]}" for c in CONFIGS])
def test_sa_core(s: int, ind: int, accd: int) -> None:
    run(
        toplevel="sa_core",
        sources=rtl(*SOURCES),
        test_module="tb.core.cocotb_core",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "IN_DEPTH": ind, "ACC_DEPTH": accd, "DATA_W": 8, "ACC_W": 32},
    )
