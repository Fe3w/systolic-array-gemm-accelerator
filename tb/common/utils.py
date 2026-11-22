"""Small helpers shared by cocotb testbenches."""

from __future__ import annotations

import json
import logging
import os
import random

from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.types import Logic

_log = logging.getLogger("cocotb.sysarray")


def get_seed() -> int:
    """The seed chosen by tb/common/runner.py (exported as SYSARRAY_SEED)."""
    env = os.environ.get("SYSARRAY_SEED")
    if env is None or env.strip() == "":
        raise RuntimeError("SYSARRAY_SEED not set; run tests through tb/common/runner.py")
    return int(env, 0)


def get_params() -> dict[str, int]:
    """HDL parameters of the current build (exported by the runner as SYSARRAY_PARAMS)."""
    return {k: int(v) for k, v in json.loads(os.environ.get("SYSARRAY_PARAMS", "{}")).items()}


def get_rng(salt: str = "") -> random.Random:
    """A private, seeded RNG for one test. ``salt`` (the test name) keeps tests independent,
    so adding or reordering tests does not change another test's stimulus."""
    seed = get_seed()
    _log.info("SYSARRAY_SEED=%d salt=%r", seed, salt)
    return random.Random(f"{seed}:{salt}")


def to_unsigned(value: int, width: int) -> int:
    """Two's-complement bit pattern of a signed ``value`` in ``width`` bits."""
    lo, hi = -(1 << (width - 1)), (1 << width) - 1
    if not lo <= value <= hi:
        raise ValueError(f"{value} does not fit in {width} bits")
    return value & ((1 << width) - 1)


def to_signed(value: int, width: int) -> int:
    """Signed value of a ``width``-bit two's-complement bit pattern."""
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def rand_signed(rng: random.Random, width: int) -> int:
    return rng.randint(-(1 << (width - 1)), (1 << (width - 1)) - 1)


def start_clock(clk, period_ns: int = 10) -> Clock:
    """Start a free-running clock on ``clk`` (cocotb 2.x: ``start()`` runs its own task)."""
    clock = Clock(clk, period_ns, unit="ns")
    clock.start()
    return clock


async def reset_sync(clk, rst, cycles: int = 2) -> None:
    """Synchronous active-high reset (D-005): hold ``rst`` high for ``cycles`` rising edges."""
    rst.value = 1
    for _ in range(cycles):
        await RisingEdge(clk)
    rst.value = 0


def pack(values: list[int], width: int) -> int:
    """Pack signed elements into one integer; element 0 occupies the low ``width`` bits.

    Matches SystemVerilog packed ports declared ``[N-1:0][width-1:0]``.
    """
    word = 0
    for i, v in enumerate(values):
        word |= to_unsigned(v, width) << (i * width)
    return word


def unpack(word: int, width: int, count: int) -> list[int]:
    """Inverse of :func:`pack`: ``count`` signed elements of ``width`` bits each."""
    return [to_signed(word >> (i * width), width) for i in range(count)]


async def drive_cycles(
    dut,
    stimulus: list[dict[str, int]],
    sample: list[str],
    defaults: dict[str, int],
) -> list[dict[str, int]]:
    """Drive one input dict per cycle and sample outputs, using the shared convention.

    Iteration k waits for a falling edge, samples ``sample`` (registered state after
    the previous rising edge = the outputs visible in "cycle k"), then drives
    ``defaults`` updated with ``stimulus[k]`` (the inputs of "cycle k", captured at
    the next rising edge). This matches the cycle numbering of docs/spec/*.md:
    inputs presented in cycle t produce registered outputs visible in cycle t + 1.

    Returns one dict of raw (unsigned) integer values per cycle. An output that is
    not 0/1-resolvable (X/Z) is returned as -1 so a comparison fails loudly.
    """
    observed: list[dict[str, int]] = []
    for inputs in stimulus:
        await FallingEdge(dut.clk)
        row = {}
        for name in sample:
            v = getattr(dut, name).value
            if not v.is_resolvable:
                row[name] = -1
            elif isinstance(v, Logic):  # 1-bit signals come back as Logic in cocotb 2.x
                row[name] = int(v)
            else:
                row[name] = v.to_unsigned()
        observed.append(row)
        for name, value in {**defaults, **inputs}.items():
            getattr(dut, name).value = value
    return observed
