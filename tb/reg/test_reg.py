"""pytest launcher for the sa_reg cocotb tests (tb/reg/cocotb_reg.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run

# (W, D): byte-wide single stage (PE use), multi-stage (skew line), wire, odd width, psum width.
CONFIGS = [(8, 1), (8, 3), (8, 0), (17, 5), (32, 2), (1, 4)]


@pytest.mark.parametrize(("w", "d"), CONFIGS, ids=[f"W{w}_D{d}" for w, d in CONFIGS])
def test_sa_reg(w: int, d: int) -> None:
    run(
        toplevel="sa_reg",
        sources=rtl("common/sa_reg.sv"),
        test_module="tb.reg.cocotb_reg",
        block_dir=Path(__file__).parent,
        parameters={"W": w, "D": d},
    )
