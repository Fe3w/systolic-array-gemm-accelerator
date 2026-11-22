"""pytest launcher for the sa_acc cocotb tests (tb/acc/cocotb_acc.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

CONFIGS = [(4, 32), (8, 256)]  # (S, ACC_DEPTH)


@pytest.mark.parametrize(("s", "depth"), CONFIGS, ids=[f"S{s}_D{d}" for s, d in CONFIGS])
def test_sa_acc(s: int, depth: int) -> None:
    run(
        toplevel="sa_acc",
        sources=rtl("mem/sa_sram.sv", "mem/sa_acc.sv"),
        test_module="tb.acc.cocotb_acc",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "ACC_DEPTH": depth, "ACC_W": 32},
    )
