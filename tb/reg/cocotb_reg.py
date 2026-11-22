"""cocotb tests for rtl/common/sa_reg.sv: a W-bit, D-stage pipeline register with a valid bit.

Contract (docs/spec/pe.md §"Shared pipeline register", decision D-005):
  * out_data/out_valid at cycle t equal in_data/in_valid at cycle t - D.
  * D = 0 is a plain wire (combinational pass-through).
  * Synchronous active-high rst clears every valid bit; data registers are not reset.

Timing convention used by every check below:
  inputs are driven just after a FALLING edge, outputs are sampled 1 ns later
  (still before the next rising edge). With that convention, after t rising edges
  stage D-1 holds the input driven D falling edges ago.
"""

from __future__ import annotations

from collections import deque

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from tb.common.utils import get_params, get_rng, reset_sync, start_clock


def _cfg() -> tuple[int, int]:
    p = get_params()
    return p["W"], p["D"]


async def _setup(dut) -> None:
    start_clock(dut.clk)
    dut.in_valid.value = 0
    dut.in_data.value = 0
    await reset_sync(dut.clk, dut.rst, cycles=2)


async def _drive_and_sample(dut, valid: int, data: int) -> tuple[int, int | None]:
    """Drive inputs after a falling edge; return (out_valid, out_data or None if unresolved)."""
    await FallingEdge(dut.clk)
    dut.in_valid.value = valid
    dut.in_data.value = data
    await Timer(1, unit="ns")
    out_valid = int(dut.out_valid.value)
    raw = dut.out_data.value
    out_data = raw.to_unsigned() if raw.is_resolvable else None
    return out_valid, out_data


@cocotb.test()
async def test_random_stream_delay(dut) -> None:
    """300 cycles of random valid/data: output is exactly the input D cycles earlier."""
    width, depth = _cfg()
    rng = get_rng("test_random_stream_delay")
    await _setup(dut)

    # history[i] = (valid, data) driven i calls ago; seeded with D empty slots (post-reset).
    history: deque[tuple[int, int]] = deque([(0, 0)] * depth, maxlen=depth + 1)
    checked = 0
    for cycle in range(300):
        valid = int(rng.random() < 0.7)
        data = rng.getrandbits(width)
        history.appendleft((valid, data))
        out_valid, out_data = await _drive_and_sample(dut, valid, data)
        exp_valid, exp_data = history[depth]
        assert out_valid == exp_valid, f"cycle {cycle}: out_valid={out_valid}, expected {exp_valid}"
        if exp_valid:
            assert out_data == exp_data, f"cycle {cycle}: out_data={out_data}, expected {exp_data}"
            checked += 1
    assert checked > 100, "too few valid samples checked"
    dut._log.info("W=%d D=%d: %d valid samples checked", width, depth, checked)


@cocotb.test()
async def test_corner_data_values(dut) -> None:
    """All-zeros, all-ones, MSB-only and LSB-only patterns pass through unchanged."""
    width, depth = _cfg()
    await _setup(dut)
    patterns = [0, (1 << width) - 1, 1 << (width - 1), 1]
    history: deque[tuple[int, int]] = deque([(0, 0)] * depth, maxlen=depth + 1)
    for cycle, data in enumerate(patterns + [0] * (depth + 1)):
        valid = int(cycle < len(patterns))
        history.appendleft((valid, data))
        out_valid, out_data = await _drive_and_sample(dut, valid, data)
        exp_valid, exp_data = history[depth]
        assert out_valid == exp_valid, f"cycle {cycle}"
        if exp_valid:
            assert out_data == exp_data, f"cycle {cycle}: {out_data:#x} != {exp_data:#x}"


@cocotb.test()
async def test_reset_while_input_valid(dut) -> None:
    """Valid inputs during reset must never appear at the output after reset (D-005)."""
    width, depth = _cfg()
    rng = get_rng("test_reset_while_input_valid")
    start_clock(dut.clk)
    dut.rst.value = 1
    dut.in_valid.value = 1
    for _ in range(depth + 3):
        dut.in_data.value = rng.getrandbits(width)
        await RisingEdge(dut.clk)
    # Release reset and stop driving valid on the same falling edge.
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.in_valid.value = 0
    for cycle in range(depth + 3):
        await Timer(1, unit="ns")
        assert int(dut.out_valid.value) == 0, f"stale valid {cycle} cycles after reset"
        await FallingEdge(dut.clk)


@cocotb.test()
async def test_reset_mid_stream_flushes(dut) -> None:
    """A one-cycle reset in the middle of a valid stream clears every in-flight valid bit."""
    width, depth = _cfg()
    if depth == 0:
        dut._log.info("D=0 has no state to flush; nothing to check")
        return
    await _setup(dut)
    # Fill the pipeline with valid data.
    for _ in range(depth + 1):
        await FallingEdge(dut.clk)
        dut.in_valid.value = 1
        dut.in_data.value = (1 << width) - 1
    # One-cycle reset with the input idle.
    await FallingEdge(dut.clk)
    dut.rst.value = 1
    dut.in_valid.value = 0
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    for cycle in range(depth + 2):
        await Timer(1, unit="ns")
        assert int(dut.out_valid.value) == 0, f"valid survived reset ({cycle} cycles after)"
        await FallingEdge(dut.clk)


@cocotb.test()
async def test_latency_is_exactly_d(dut) -> None:
    """A single valid pulse appears exactly D cycles later and only once."""
    width, depth = _cfg()
    await _setup(dut)
    seen_at = []
    for cycle in range(depth + 5):
        valid = int(cycle == 0)
        out_valid, _ = await _drive_and_sample(dut, valid, 0x5 & ((1 << width) - 1))
        if out_valid:
            seen_at.append(cycle)
    assert seen_at == [depth], f"pulse seen at cycles {seen_at}, expected [{depth}]"
