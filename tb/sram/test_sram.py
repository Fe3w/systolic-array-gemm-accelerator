"""pytest launcher for the sa_sram cocotb tests (tb/sram/cocotb_sram.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

# (WIDTH, DEPTH): small odd-width memory, an S = 8 input buffer, a weight buffer, depth 1.
CONFIGS = [(16, 8), (64, 256), (32, 4), (8, 1)]


@pytest.mark.parametrize(("width", "depth"), CONFIGS, ids=[f"W{w}_D{d}" for w, d in CONFIGS])
def test_sa_sram(width: int, depth: int) -> None:
    run(
        toplevel="sa_sram",
        sources=rtl("mem/sa_sram.sv"),
        test_module="tb.sram.cocotb_sram",
        block_dir=Path(__file__).parent,
        parameters={"WIDTH": width, "DEPTH": depth},
    )
