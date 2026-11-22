"""pytest launcher for the verification campaign (tb/campaign/cocotb_campaign.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tb.common.runner import rtl, run
from tb.top.test_top import SOURCES


@pytest.mark.parametrize("s", [4, 8])
def test_campaign(s: int) -> None:
    run(
        toplevel="sa_top",
        sources=rtl(*SOURCES),
        test_module="tb.campaign.cocotb_campaign",
        block_dir=Path(__file__).parent,
        parameters={"S": s},
    )
