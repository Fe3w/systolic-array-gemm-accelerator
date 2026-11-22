"""pytest launcher for the sa_feed_top cocotb tests (tb/feed/cocotb_feed.py)."""

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
    "array/sa_feeder.sv",
    "array/sa_feed_top.sv",
)
# (S, IN_DEPTH): bring-up size with a small buffer, then the D-016 sizes at S = 4 and S = 8.
CONFIGS = [(4, 16), (4, 256), (8, 256)]


@pytest.mark.parametrize(("s", "depth"), CONFIGS, ids=[f"S{s}_D{d}" for s, d in CONFIGS])
def test_sa_feed_top(s: int, depth: int) -> None:
    run(
        toplevel="sa_feed_top",
        sources=rtl(*SOURCES),
        test_module="tb.feed.cocotb_feed",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "IN_DEPTH": depth, "DATA_W": 8, "ACC_W": 32},
    )
