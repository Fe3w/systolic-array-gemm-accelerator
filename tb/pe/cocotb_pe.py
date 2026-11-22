"""cocotb tests for rtl/pe/sa_pe.sv, written from docs/spec/pe.md §6 before the RTL.

Contract (docs/spec/pe.md §1, decisions D-004a, D-005a, D-011, D-012):
  p_q      <= a_valid_in ? a_in * w_q : 0                (stage 1, M7b)
  psum_out <= psum_in + p_q                               (stage 2, int32 wrap)
  a_out <= a_in;  a_valid_out <= a_valid_in (reset to 0)
  w_q <= w_load ? w_in : w_q;  w_out = w_q

Timing convention (same as tb/reg): every call to ``_cycle`` waits for a
falling edge, samples the registered outputs (state after the previous rising
edge), then drives the next inputs. So outputs returned by call k are the
response to the inputs driven in call k - 1.

Expected values come from ``sysarray.golden.to_int32`` (the golden model).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from sysarray.golden import to_int32
from tb.common.utils import get_rng, rand_signed, reset_sync, start_clock, to_unsigned

DATA_W = 8
ACC_W = 32
INT8 = range(-128, 128)
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


@dataclass
class Out:
    w_out: int
    a_out: int
    a_valid_out: int
    psum_out: int


def _expected_psum(psum_in: int, a: int, w: int, valid: int) -> int:
    return int(to_int32(psum_in + (a * w if valid else 0)))


async def _setup(dut) -> None:
    start_clock(dut.clk)
    dut.w_load.value = 0
    dut.w_in.value = 0
    dut.a_in.value = 0
    dut.a_valid_in.value = 0
    dut.psum_in.value = 0
    await reset_sync(dut.clk, dut.rst, cycles=2)


async def _cycle(
    dut,
    *,
    w_load: int = 0,
    w_in: int = 0,
    a_in: int = 0,
    a_valid_in: int = 0,
    psum_in: int = 0,
) -> Out:
    """Sample outputs at the falling edge, then drive the next inputs."""
    await FallingEdge(dut.clk)
    out = Out(
        w_out=dut.w_out.value.to_signed(),
        a_out=dut.a_out.value.to_signed(),
        a_valid_out=int(dut.a_valid_out.value),
        psum_out=dut.psum_out.value.to_signed(),
    )
    dut.w_load.value = w_load
    dut.w_in.value = to_unsigned(w_in, DATA_W)
    dut.a_in.value = to_unsigned(a_in, DATA_W)
    dut.a_valid_in.value = a_valid_in
    dut.psum_in.value = to_unsigned(psum_in, ACC_W)
    return out


async def _load_weight(dut, w: int) -> None:
    """One w_load cycle; w_q holds w from the next rising edge on."""
    await _cycle(dut, w_load=1, w_in=w)


async def _mac_stream(dut, w: int, ops: list[tuple[int, int, int]], label: str) -> None:
    """Load w, then apply ops = [(a, valid, psum_in), ...] and check each psum_out.

    Two-stage MAC (docs/spec/pe.md §1, M7b): op k's activation is driven in call k,
    its psum_in in call k + 1, and its sum is visible in call k + 2.
    """
    await _load_weight(dut, w)
    n = len(ops)
    outs: list[Out] = []
    for k in range(n + 2):
        a, valid = (ops[k][0], ops[k][1]) if k < n else (0, 0)
        psum = ops[k - 1][2] if 1 <= k <= n else 0
        outs.append(await _cycle(dut, a_in=a, a_valid_in=valid, psum_in=psum))
    for k, (a, valid, psum) in enumerate(ops):
        out = outs[k + 2] if k + 2 < len(outs) else await _cycle(dut)
        exp = _expected_psum(psum, a, w, valid)
        assert out.psum_out == exp, (
            f"{label}: w={w} a={a} valid={valid} psum_in={psum}: "
            f"psum_out={out.psum_out}, expected {exp}"
        )
        assert out.w_out == w, f"{label}: weight changed to {out.w_out} (expected {w})"


@cocotb.test()
async def test_exhaustive_products(dut) -> None:
    """All 65,536 int8 x int8 products with psum_in = 0 (spec test 1)."""
    await _setup(dut)
    for w in INT8:
        await _mac_stream(dut, w, [(a, 1, 0) for a in INT8], "exhaustive")
    dut._log.info("checked %d products", 256 * 256)


@cocotb.test()
async def test_random_accumulate_with_wrap(dut) -> None:
    """Random full-range psum_in plus forced int32 wrap in both directions (spec test 2)."""
    rng = get_rng("test_random_accumulate_with_wrap")
    await _setup(dut)
    forced = [
        (127, 1, INT32_MAX),  # + positive product -> wraps negative (w = 127 below)
        (-128, 1, INT32_MIN),  # + negative product -> wraps positive
        (-128, 1, INT32_MAX),
        (1, 1, INT32_MIN),
    ]
    await _mac_stream(dut, 127, forced, "forced-wrap w=127")
    await _mac_stream(dut, -128, forced, "forced-wrap w=-128")

    def psum_value() -> int:
        # A uniform int32 is almost never within 2**14 of a limit, so a third of the
        # values are drawn next to INT32_MAX / INT32_MIN to make random wraps common.
        r = rng.random()
        if r < 1 / 6:
            return INT32_MAX - rng.randint(0, 2**14)
        if r < 1 / 3:
            return INT32_MIN + rng.randint(0, 2**14)
        return rand_signed(rng, ACC_W)

    wraps = 0
    for _ in range(20):
        w = rand_signed(rng, DATA_W)
        ops = [(rand_signed(rng, DATA_W), 1, psum_value()) for _ in range(50)]
        wraps += sum(1 for a, _, p in ops if not INT32_MIN <= p + a * w <= INT32_MAX)
        await _mac_stream(dut, w, ops, "random")
    dut._log.info("random accumulate: 1000 ops, %d wrapped", wraps)


@cocotb.test()
async def test_corners(dut) -> None:
    """-128*-128, -128*127, 127*127, 0*x, x*0 (spec test 3)."""
    await _setup(dut)
    await _mac_stream(dut, -128, [(-128, 1, 0), (127, 1, 0), (0, 1, 0), (-128, 1, -5)], "w=-128")
    await _mac_stream(dut, 127, [(127, 1, 0), (-128, 1, 0), (0, 1, 7)], "w=127")
    await _mac_stream(dut, 0, [(-128, 1, 0), (127, 1, 0), (55, 1, 123456)], "w=0")


@cocotb.test()
async def test_weight_hold(dut) -> None:
    """With w_load = 0 the weight never changes while activations and w_in change (test 4)."""
    rng = get_rng("test_weight_hold")
    await _setup(dut)
    w = -77
    await _load_weight(dut, w)
    history: list[int] = []  # activations driven so far; psum_out lags them by 2 cycles
    for _ in range(100):
        a = rand_signed(rng, DATA_W)
        out = await _cycle(dut, w_load=0, w_in=rand_signed(rng, DATA_W), a_in=a, a_valid_in=1)
        if len(history) >= 2:
            assert out.w_out == w
            assert out.psum_out == _expected_psum(0, history[-2], w, 1)
        history.append(a)


@cocotb.test()
async def test_weight_shift_through(dut) -> None:
    """w_out = w_in of the previous cycle while w_load = 1; holds when w_load = 0 (test 5)."""
    rng = get_rng("test_weight_shift_through")
    await _setup(dut)
    expected_w = None
    for i in range(200):
        load = int(rng.random() < 0.6)
        w_in = rand_signed(rng, DATA_W)
        out = await _cycle(dut, w_load=load, w_in=w_in)
        if expected_w is not None:
            assert out.w_out == expected_w, f"cycle {i}: w_out={out.w_out}, expected {expected_w}"
        if load:
            expected_w = w_in


@cocotb.test()
async def test_activation_propagation(dut) -> None:
    """a_out / a_valid_out equal the inputs one cycle earlier (test 6)."""
    rng = get_rng("test_activation_propagation")
    await _setup(dut)
    await _load_weight(dut, 3)
    prev = (0, 0)
    for i in range(300):
        a, v = rand_signed(rng, DATA_W), int(rng.random() < 0.5)
        out = await _cycle(dut, a_in=a, a_valid_in=v)
        assert out.a_valid_out == prev[1], f"cycle {i}: a_valid_out={out.a_valid_out}"
        if i > 0:
            assert out.a_out == prev[0], f"cycle {i}: a_out={out.a_out}, expected {prev[0]}"
        prev = (a, v)


@cocotb.test()
async def test_invalid_activation_passes_psum(dut) -> None:
    """a_valid_in = 0 with non-zero a_in gives psum_out == psum_in (test 7, D-011)."""
    rng = get_rng("test_invalid_activation_passes_psum")
    await _setup(dut)
    ops = []
    for _ in range(200):
        a = rand_signed(rng, DATA_W) or 1  # non-zero, so a missing gate would show
        ops.append((a, int(rng.random() < 0.5), rand_signed(rng, ACC_W)))
    await _mac_stream(dut, -128, ops, "gated")


@cocotb.test()
async def test_reset(dut) -> None:
    """Valid during reset never appears after it; a mid-stream reset clears a_valid_out (test 8)."""
    start_clock(dut.clk)
    dut.w_load.value = 0
    dut.w_in.value = 0
    dut.psum_in.value = 0
    dut.a_in.value = 0x55
    dut.a_valid_in.value = 1
    dut.rst.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.a_valid_in.value = 0
    for i in range(3):
        out = await _cycle(dut)
        assert out.a_valid_out == 0, f"stale a_valid_out {i} cycles after reset"
    # Mid-stream: valid stream, then one reset cycle with the input idle.
    await _cycle(dut, a_in=9, a_valid_in=1)
    out = await _cycle(dut, a_in=9, a_valid_in=1)
    assert out.a_valid_out == 1
    await FallingEdge(dut.clk)
    dut.rst.value = 1
    dut.a_valid_in.value = 0
    await FallingEdge(dut.clk)
    assert int(dut.a_valid_out.value) == 0, "reset did not clear a_valid_out"
    dut.rst.value = 0
    out = await _cycle(dut)
    assert out.a_valid_out == 0
