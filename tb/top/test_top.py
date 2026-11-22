"""pytest launcher for the sa_top cocotb tests (tb/top/cocotb_top.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

SOURCES = (
    "ctrl/sa_pkg.sv",
    "common/sa_reg.sv",
    "pe/sa_pe.sv",
    "array/sa_grid.sv",
    "array/sa_array.sv",
    "mem/sa_sram.sv",
    "mem/sa_acc.sv",
    "array/sa_feeder.sv",
    "dma/sa_dma.sv",
    "core/sa_core.sv",
    "ctrl/sa_ctrl.sv",
    "top/sa_top.sv",
)


@pytest.mark.parametrize("s", [4, 8])
def test_sa_top(s: int) -> None:
    run(
        toplevel="sa_top",
        sources=rtl(*SOURCES),
        test_module="tb.top.cocotb_top",
        block_dir=Path(__file__).parent,
        parameters={"S": s},
    )
