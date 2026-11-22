"""pytest launcher for the sa_dma cocotb tests (tb/dma/cocotb_dma.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

SOURCES = ("mem/sa_sram.sv", "dma/sa_dma.sv", "dma/sa_dma_top.sv")
CONFIGS = [(4, 32, 16), (8, 256, 256)]  # (S, IN_DEPTH, ACC_DEPTH)


@pytest.mark.parametrize(("s", "ind", "accd"), CONFIGS, ids=[f"S{c[0]}" for c in CONFIGS])
def test_sa_dma(s: int, ind: int, accd: int) -> None:
    run(
        toplevel="sa_dma_top",
        sources=rtl(*SOURCES),
        test_module="tb.dma.cocotb_dma",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "IN_DEPTH": ind, "ACC_DEPTH": accd, "DATA_W": 8, "ACC_W": 32},
    )
