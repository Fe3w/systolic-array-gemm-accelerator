"""Tests for sysarray.tiler and sysarray.funcsim (M9).

The tiler's programs are executed by the functional command simulator (the
command semantics of docs/spec/ctrl.md §1) and compared with golden.gemm, for
shapes that are and are not multiples of S, in both tile orders.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from sysarray import funcsim, golden, tiler
from sysarray.commands import ACCUMULATE, DEPTH, OP_COMPUTE, OP_LOAD_A, OP_LOAD_W, OP_STORE, Command


def _rng() -> np.random.Generator:
    seed = int(os.environ.get("SYSARRAY_SEED", "20261112"))
    print(f"SYSARRAY_SEED={seed}")
    return np.random.default_rng(seed)


def _rand(rng: np.random.Generator, shape: tuple[int, int]) -> np.ndarray:
    return rng.integers(-128, 128, size=shape)


def _run(prog: tiler.Program) -> np.ndarray:
    mem = bytearray(prog.mem_size)
    for addr, data in prog.image:
        mem[addr : addr + len(data)] = data
    funcsim.execute(prog.commands, mem, prog.s)
    return prog.read_c(mem)


SHAPES = [(1, 1, 1), (8, 8, 8), (3, 5, 7), (13, 9, 11), (17, 23, 29), (100, 37, 53), (300, 9, 8)]


@pytest.mark.parametrize("order", ["A", "B"])
@pytest.mark.parametrize(("m", "n", "k"), SHAPES)
@pytest.mark.parametrize("s", [4, 8])
def test_program_matches_golden(order: str, m: int, n: int, k: int, s: int) -> None:
    rng = _rng()
    a, b = _rand(rng, (m, k)), _rand(rng, (k, n))
    prog = tiler.tile(a, b, s=s, order=order)
    np.testing.assert_array_equal(_run(prog), golden.gemm(a, b))


def test_m_chunk_smaller_than_m() -> None:
    rng = _rng()
    a, b = _rand(rng, (37, 16)), _rand(rng, (16, 12))
    for order in ("A", "B"):
        prog = tiler.tile(a, b, s=4, order=order, m_c=10)
        np.testing.assert_array_equal(_run(prog), golden.gemm(a, b))


def test_padding_counts_and_bytes() -> None:
    a, b = np.ones((5, 7), dtype=np.int64), np.ones((7, 9), dtype=np.int64)
    prog = tiler.tile(a, b, s=4, order="A")
    st = prog.stats
    assert (st.kp, st.np_) == (8, 12)
    assert st.useful_macs == 5 * 9 * 7
    assert st.issued_macs == 4 * 4 * 5 * (8 // 4) * (12 // 4)  # S^2 per row per tile
    # M11b: the partial last k-tile reads only K % S = 3 real weight rows
    assert st.weight_bytes == 4 * (4 + 3) * (12 // 4)
    assert st.act_bytes == 5 * 4 * (8 // 4) * (12 // 4)  # order A reloads A per n tile
    assert st.out_bytes == 5 * 12 * 4


def test_order_b_reloads_weights_per_m_chunk() -> None:
    a, b = np.ones((20, 8), dtype=np.int64), np.ones((8, 8), dtype=np.int64)
    sa = tiler.tile(a, b, s=4, order="A", m_c=5).stats
    sb = tiler.tile(a, b, s=4, order="B", m_c=5).stats
    n_tiles = (8 // 4) * (8 // 4)
    assert sa.weight_bytes == 16 * n_tiles  # each weight tile once
    assert sb.weight_bytes == 16 * n_tiles * 4  # once per m chunk (20 / 5)


def test_no_compute_follows_compute() -> None:
    """Both orders put a LOAD_A (or LOAD_W) between COMPUTEs (D-024 gap stays hidden)."""
    a, b = np.ones((30, 12), dtype=np.int64), np.ones((12, 8), dtype=np.int64)
    for order in ("A", "B"):
        ops = [c.op for c in tiler.tile(a, b, s=4, order=order, m_c=7).commands]
        assert all(not (x == y == OP_COMPUTE) for x, y in zip(ops, ops[1:], strict=False))


def test_rejects_bad_arguments() -> None:
    a = np.ones((2, 2), dtype=np.int64)
    with pytest.raises(ValueError, match="order"):
        tiler.tile(a, a, s=4, order="C")
    with pytest.raises(ValueError, match="m_c"):
        tiler.tile(a, a, s=4, order="A", m_c=257)


def test_funcsim_semantics_small() -> None:
    """Directed check of the four commands against spec §1 (S = 2)."""
    mem = bytearray(256)
    mem[0:4] = bytes([1, 2, 3, 4])  # weights rows [1,2], [3,4]
    mem[16:20] = np.array([1, -1, 2, 0], dtype=np.int8).tobytes()  # A rows [1,-1], [2,0]
    prog = [
        Command(op=OP_LOAD_W, mem_addr=0, mem_stride=2),
        Command(op=OP_LOAD_A, mem_addr=16, mem_stride=2, rows=2),
        Command(op=OP_COMPUTE, rows=2),
        Command(op=OP_COMPUTE, acc_mode=ACCUMULATE, rows=2),
        Command(op=OP_STORE, mem_addr=64, mem_stride=8, rows=2),
    ]
    funcsim.execute(prog, mem, s=2)
    c = np.frombuffer(bytes(mem[64:80]), dtype="<i4").reshape(2, 2)
    np.testing.assert_array_equal(c, 2 * (np.array([[1, -1], [2, 0]]) @ np.array([[1, 2], [3, 4]])))


def test_partial_weight_tile_reads_only_real_rows() -> None:
    """K % S != 0: the last LOAD_W of each column strip reads K % S rows (M11b issue 7)."""
    a, b = np.ones((5, 7), dtype=np.int64), np.ones((7, 9), dtype=np.int64)
    prog = tiler.tile(a, b, s=4, order="A")
    loads = [c for c in prog.commands if c.op == OP_LOAD_W]
    assert [c.rows for c in loads] == [0, 3] * 3  # k-tile 0: full (0 = S), k-tile 1: 7 % 4 = 3
    assert prog.stats.weight_bytes == 4 * (4 + 3) * 3


def test_funcsim_partial_load_w_zero_fills() -> None:
    mem = bytearray(64)
    mem[0:4] = bytes([1, 2, 3, 4])
    mem[4:8] = bytes([9, 9, 9, 9])  # must NOT be read: only 1 of 2 rows is real
    machine = funcsim.execute([Command(op=OP_LOAD_W, mem_addr=0, mem_stride=4, rows=1)], mem, s=2)
    np.testing.assert_array_equal(machine.weights, np.array([[1, 2], [0, 0]]))


def test_ping_pong_input_halves() -> None:
    """M13: with m_c <= 128, LOAD_As alternate between the two input-buffer halves
    and every COMPUTE reads the rows of the latest LOAD_A before it."""
    a, b = np.ones((300, 16), dtype=np.int64), np.ones((16, 16), dtype=np.int64)
    for order in ("A", "B"):
        prog = tiler.tile(a, b, s=4, order=order)
        assert prog.stats.m_c == DEPTH // 2
        loads = [c for c in prog.commands if c.op == OP_LOAD_A]
        assert [c.buf_addr for c in loads[:4]] == [0, DEPTH // 2, 0, DEPTH // 2]
        last = None
        for c in prog.commands:
            if c.op == OP_LOAD_A:
                last = c
            elif c.op == OP_COMPUTE:
                assert last is not None
                assert (c.buf_addr, c.rows) == (last.buf_addr, last.rows)


def test_load_a_hoisted_before_load_w_and_store() -> None:
    """M13: a LOAD_A is moved ahead of the LOAD_W / STORE before it, so its DMA
    overlaps the previous COMPUTE instead of waiting behind the weight reload."""
    a, b = np.ones((40, 12), dtype=np.int64), np.ones((12, 12), dtype=np.int64)
    for order in ("A", "B"):
        ops = [c.op for c in tiler.tile(a, b, s=4, order=order).commands]
        pairs = list(zip(ops, ops[1:], strict=False))
        assert (OP_LOAD_W, OP_LOAD_A) not in pairs
        assert (OP_STORE, OP_LOAD_A) not in pairs


def test_predicted_utilization_with_overlap() -> None:
    """Predicted (analytical): sq256 order A, S = 8 rises from the M11 measurement
    0.4409 (results/perf/f5c0a0c.csv) to > 0.7 with double buffering."""
    from sysarray import predict

    a, b = np.ones((256, 256), dtype=np.int64), np.ones((256, 256), dtype=np.int64)
    prog = tiler.tile(a, b, s=8, order="A")
    p = predict.predict(prog.commands, s=8, read_latency=3, useful_macs=prog.stats.useful_macs)
    print(f"predicted utilization {p.utilization:.4f}, cycles {p.cycles_total}")
    assert p.utilization is not None and p.utilization > 0.7
