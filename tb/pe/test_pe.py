"""pytest launcher for the sa_pe cocotb tests (tb/pe/cocotb_pe.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import REPO_ROOT, rtl, run

DSP_MODEL = REPO_ROOT / "tb" / "models" / "MULT18X18D.v"


@pytest.mark.parametrize("dsp", [False, True], ids=["behavioural", "ecp5_dsp"])
def test_sa_pe(dsp: bool) -> None:
    """dsp=True builds the `SA_ECP5_DSP` form with the MULT18X18D model (M11b)."""
    run(
        toplevel="sa_pe",
        sources=rtl("pe/sa_pe.sv") + ([DSP_MODEL] if dsp else []),
        defines={"SA_ECP5_DSP": 1} if dsp else None,
        test_module="tb.pe.cocotb_pe",
        block_dir=Path(__file__).parent,
        parameters={"DATA_W": 8, "ACC_W": 32},
    )
