"""cocotb tests for rtl/mem/sa_acc.sv, from docs/spec/acc.md §1 and §3.

Model: a Python list of rows. Since M13 every output row carries its own tag
(c_mode, c_addr): row j of a COMPUTE with base b arrives with c_addr = b + j and
updates that row by overwrite or element-wise int32 wrap add.
Rows are read back through the STORE port (1-cycle latency) and compared.
"""

from __future__ import annotations

import cocotb

from sysarray.golden import to_int32
from tb.common.utils import (
    drive_cycles,
    get_params,
    get_rng,
    pack,
    rand_signed,
    start_clock,
    unpack,
)

ACC_W = 32
OVERWRITE, ACCUMULATE = 0, 1
DEFAULTS = {
    "rst": 0,
    "c_valid": 0,
    "c_mode": 0,
    "c_addr": 0,
    "c_row": 0,
    "st_re": 0,
    "st_raddr": 0,
}


class AccModel:
    def __init__(self, s: int, depth: int) -> None:
        self.s, self.depth = s, depth
        self.rows: list[list[int] | None] = [None] * depth
        self.stim: list[dict[str, int]] = []

    def compute(self, mode: int, base: int, out_rows: list[list[int]], gap: int = 0) -> None:
        """`gap` idle cycles, then one tagged output row per cycle."""
        self.stim += [{} for _ in range(gap)]
        for j, row in enumerate(out_rows):
            self.stim.append(
                {"c_valid": 1, "c_mode": mode, "c_addr": base + j, "c_row": pack(row, ACC_W)}
            )
            old = self.rows[base + j]
            if mode == OVERWRITE or old is None:
                assert mode == OVERWRITE, "ACCUMULATE into an unwritten row"
                self.rows[base + j] = list(row)
            else:
                self.rows[base + j] = [int(to_int32(a + b)) for a, b in zip(old, row, strict=True)]

    def idle(self, n: int) -> None:
        self.stim += [{} for _ in range(n)]


async def _readback(dut, model: AccModel, label: str) -> None:
    addrs = [a for a, r in enumerate(model.rows) if r is not None]
    stim = [{"st_re": 1, "st_raddr": a} for a in addrs] + [{}]
    observed = await drive_cycles(dut, stim, ["st_rdata"], DEFAULTS)
    for i, a in enumerate(addrs):
        got = unpack(observed[i + 1]["st_rdata"], ACC_W, model.s)
        assert got == model.rows[a], f"{label}: row {a}: {got} != {model.rows[a]}"


async def _setup(dut) -> tuple[int, int]:
    p = get_params()
    start_clock(dut.clk)
    for k, v in DEFAULTS.items():
        getattr(dut, k).value = v
    dut.rst.value = 1
    await drive_cycles(dut, [{"rst": 1}, {"rst": 1}], [], DEFAULTS)
    return p["S"], p["ACC_DEPTH"]


def _rows(rng, n: int, s: int) -> list[list[int]]:
    return [[rand_signed(rng, ACC_W) for _ in range(s)] for _ in range(n)]


@cocotb.test()
async def test_overwrite_then_accumulate(dut) -> None:
    """OVERWRITE rows, then ACCUMULATE two more passes over the same rows."""
    rng = get_rng("test_overwrite_then_accumulate")
    s, depth = await _setup(dut)
    model = AccModel(s, depth)
    n = min(20, depth)
    model.compute(OVERWRITE, 0, _rows(rng, n, s))
    model.idle(5)
    model.compute(ACCUMULATE, 0, _rows(rng, n, s))
    model.idle(5)
    model.compute(ACCUMULATE, 0, _rows(rng, n, s))
    model.idle(3)
    await drive_cycles(dut, model.stim, [], DEFAULTS)
    await _readback(dut, model, "3 passes")


@cocotb.test()
async def test_wrap(dut) -> None:
    """ACCUMULATE wraps at 32 bits per element (D-004a)."""
    s, depth = await _setup(dut)
    model = AccModel(s, depth)
    big = 2**31 - 1
    model.compute(OVERWRITE, depth - 1, [[big] * s])
    model.idle(3)
    model.compute(ACCUMULATE, depth - 1, [[1] * s])
    model.idle(3)
    await drive_cycles(dut, model.stim, [], DEFAULTS)
    await _readback(dut, model, "wrap")
    assert model.rows[depth - 1] == [-(2**31)] * s


@cocotb.test()
async def test_closest_spacing_same_rows(dut) -> None:
    """A new ACCUMULATE COMPUTE whose first row comes 3 cycles after the previous
    last row (spec §1), to the same rows, at random bases."""
    rng = get_rng("test_closest_spacing_same_rows")
    s, depth = await _setup(dut)
    model = AccModel(s, depth)
    base = rng.randint(0, depth - 8)
    model.compute(OVERWRITE, base, _rows(rng, 8, s))
    # previous last c_valid in cycle L, gap 2 -> first c_valid in L + 3 (same rows)
    model.compute(ACCUMULATE, base, _rows(rng, 8, s), gap=2)
    model.compute(ACCUMULATE, base + 4, _rows(rng, 4, s), gap=2)
    model.idle(3)
    await drive_cycles(dut, model.stim, [], DEFAULTS)
    await _readback(dut, model, "closest spacing")


@cocotb.test()
async def test_back_to_back_tags(dut) -> None:
    """Rows of different COMPUTEs (modes, bases) in consecutive cycles, no gap (M13).

    Before M13 the configuration was latched per COMPUTE, so this needed the
    D-024 gap; with per-row tags any distinct rows may follow each other.
    """
    rng = get_rng("test_back_to_back_tags")
    s, depth = await _setup(dut)
    model = AccModel(s, depth)
    half = depth // 2
    model.compute(OVERWRITE, 0, _rows(rng, 4, s))
    model.compute(OVERWRITE, half, _rows(rng, 3, s))
    model.compute(ACCUMULATE, 2, _rows(rng, 2, s), gap=2)  # rows 2, 3 written >= 3 cycles ago
    model.compute(OVERWRITE, half + 3, _rows(rng, 1, s))
    model.compute(ACCUMULATE, half, _rows(rng, 2, s))
    model.idle(3)
    await drive_cycles(dut, model.stim, [], DEFAULTS)
    await _readback(dut, model, "back-to-back tags")
