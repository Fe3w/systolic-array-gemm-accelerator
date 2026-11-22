"""pytest launcher for the sa_grid cocotb tests (tb/grid/cocotb_grid.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run


@pytest.mark.parametrize("s", [4, 2, 3, 8])
def test_sa_grid(s: int) -> None:
    run(
        toplevel="sa_grid",
        sources=rtl("pe/sa_pe.sv", "array/sa_grid.sv"),
        test_module="tb.grid.cocotb_grid",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "DATA_W": 8, "ACC_W": 32},
    )
