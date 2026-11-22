"""pytest launcher for the compiler-driven GEMM tests (tb/gemm/cocotb_gemm.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run
from tb.top.test_top import SOURCES


@pytest.mark.parametrize("s", [4, 8])
def test_gemm(s: int) -> None:
    run(
        toplevel="sa_top",
        sources=rtl(*SOURCES),
        test_module="tb.gemm.cocotb_gemm",
        block_dir=Path(__file__).parent,
        parameters={"S": s},
    )
