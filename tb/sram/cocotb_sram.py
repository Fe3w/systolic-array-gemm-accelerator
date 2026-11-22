"""cocotb tests for rtl/mem/sa_sram.sv, from docs/spec/buffers.md §1 and §6 (D-017).

Model: a Python list. A read issued in cycle t (re = 1) returns, in cycle t + 1,
the contents *before* any write in cycle t (read-first). rdata holds while re = 0.
Cycle numbering as in tb.common.utils.drive_cycles.
"""

from __future__ import annotations

import cocotb

from tb.common.utils import drive_cycles, get_params, get_rng, start_clock

DEFAULTS = {"we": 0, "waddr": 0, "wdata": 0, "re": 0, "raddr": 0}


async def _setup(dut) -> tuple[int, int]:
    p = get_params()
    start_clock(dut.clk)
    for name, value in DEFAULTS.items():
        getattr(dut, name).value = value
    return p["WIDTH"], p["DEPTH"]


def _model(stim: list[dict[str, int]], depth: int) -> list[int | None]:
    """Expected rdata visible in each cycle (None = not yet defined)."""
    mem: list[int | None] = [None] * depth
    rdata: int | None = None
    expected: list[int | None] = []
    for cyc in stim:
        expected.append(rdata)
        inputs = {**DEFAULTS, **cyc}
        if inputs["re"]:
            rdata = mem[inputs["raddr"]]  # read before the write of the same edge
        if inputs["we"]:
            mem[inputs["waddr"]] = inputs["wdata"]
    return expected


async def _run_and_check(dut, stim, depth: int, label: str) -> int:
    observed = await drive_cycles(dut, stim + [{}], ["rdata"], DEFAULTS)
    expected = _model(stim + [{}], depth)
    checked = 0
    for k, (obs, exp) in enumerate(zip(observed, expected, strict=True)):
        if exp is None:
            continue
        assert (
            obs["rdata"] == exp
        ), f"{label}: cycle {k}: rdata={obs['rdata']:#x}, expected {exp:#x}"
        checked += 1
    return checked


@cocotb.test()
async def test_write_then_read_all(dut) -> None:
    """Fill every address, read every address back; 1-cycle read latency (§6 test 1)."""
    width, depth = await _setup(dut)
    rng = get_rng("test_write_then_read_all")
    data = [rng.getrandbits(width) for _ in range(depth)]
    stim = [{"we": 1, "waddr": a, "wdata": d} for a, d in enumerate(data)]
    order = list(range(depth))
    rng.shuffle(order)
    stim += [{"re": 1, "raddr": a} for a in order]
    checked = await _run_and_check(dut, stim, depth, "write-then-read")
    assert checked >= depth


@cocotb.test()
async def test_random_traffic(dut) -> None:
    """Random simultaneous reads and writes, including same-address collisions (§6 tests 1-3)."""
    width, depth = await _setup(dut)
    rng = get_rng("test_random_traffic")
    stim = [{"we": 1, "waddr": a, "wdata": rng.getrandbits(width)} for a in range(depth)]
    collisions = 0
    for _ in range(400):
        cyc: dict[str, int] = {}
        if rng.random() < 0.5:
            cyc.update(we=1, waddr=rng.randrange(depth), wdata=rng.getrandbits(width))
        if rng.random() < 0.6:
            raddr = cyc["waddr"] if "waddr" in cyc and rng.random() < 0.3 else rng.randrange(depth)
            cyc.update(re=1, raddr=raddr)
            collisions += int(cyc.get("waddr") == raddr)
        stim.append(cyc)
    await _run_and_check(dut, stim, depth, "random")
    dut._log.info("random traffic: %d same-address read/write collisions", collisions)
    assert collisions > 10


@cocotb.test()
async def test_read_during_write_returns_old(dut) -> None:
    """Directed: same-address read and write in one cycle -> old data, then new (§6 test 2)."""
    width, depth = await _setup(dut)
    old, new = 0x5 % (1 << width), ((1 << width) - 1) ^ 0x5
    addr = depth - 1
    stim = [
        {"we": 1, "waddr": addr, "wdata": old},
        {"we": 1, "waddr": addr, "wdata": new, "re": 1, "raddr": addr},
        {"re": 1, "raddr": addr},
        {},
    ]
    observed = await drive_cycles(dut, stim, ["rdata"], DEFAULTS)
    assert observed[2]["rdata"] == old, f"read-during-write returned {observed[2]['rdata']:#x}"
    assert observed[3]["rdata"] == new, f"next read returned {observed[3]['rdata']:#x}"


@cocotb.test()
async def test_rdata_holds_without_re(dut) -> None:
    """rdata keeps the last read value while re = 0, even after a rewrite (§6 test 3)."""
    width, depth = await _setup(dut)
    v1, v2 = 1, 2
    stim = [
        {"we": 1, "waddr": 0, "wdata": v1},
        {"re": 1, "raddr": 0},
        {"we": 1, "waddr": 0, "wdata": v2},
        {},
        {},
    ]
    observed = await drive_cycles(dut, stim, ["rdata"], DEFAULTS)
    assert [o["rdata"] for o in observed[2:]] == [v1, v1, v1]
