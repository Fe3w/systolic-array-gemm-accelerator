"""pytest launcher for the sa_array cocotb tests (tb/array/cocotb_array.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import REPO_ROOT, rtl, run

DSP_MODEL = REPO_ROOT / "tb" / "models" / "MULT18X18D.v"

SOURCES = ("common/sa_reg.sv", "pe/sa_pe.sv", "array/sa_grid.sv", "array/sa_array.sv")


@pytest.mark.parametrize(
    ("s", "dsp"), [(4, False), (2, False), (3, False), (8, False), (4, True), (8, True)]
)
def test_sa_array(s: int, dsp: bool) -> None:
    """dsp=True builds sa_pe's `SA_ECP5_DSP` form with the MULT18X18D model (M11b)."""
    run(
        toplevel="sa_array",
        sources=rtl(*SOURCES) + ([DSP_MODEL] if dsp else []),
        defines={"SA_ECP5_DSP": 1} if dsp else None,
        test_module="tb.array.cocotb_array",
        block_dir=Path(__file__).parent,
        parameters={"S": s, "DATA_W": 8, "ACC_W": 32},
    )
