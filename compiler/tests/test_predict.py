"""Tests for sysarray.predict (M9): a replay of the controller's timing (docs/spec/ctrl.md §3)."""

from __future__ import annotations

import numpy as np

from sysarray import predict, tiler
from sysarray.commands import OP_COMPUTE, OP_LOAD_A, OP_LOAD_W, OP_STORE, Command


def test_hand_computed_program() -> None:
    """S = 4, L = 3, R = 5, worked by hand from spec §3 (M13 concurrent dispatch,
    M11c two-cycle CHECK: a unit starts at accept + 3 at the earliest):
    LOAD_W: DMA 3..10, feeder 11..17, next accept 12; LOAD_A: DMA 15..23, next
    accept 16; COMPUTE: waits for the LOAD_A of its rows (RAW) -> feeder 24..31,
    next accept 25; STORE: waits for the COMPUTE and the gate 31 + 2S + 3 = 42 ->
    DMA 42..63 (4R + 1)."""
    prog = [
        Command(op=OP_LOAD_W, mem_stride=4),
        Command(op=OP_LOAD_A, mem_stride=4, rows=5),
        Command(op=OP_COMPUTE, rows=5),
        Command(op=OP_STORE, mem_stride=16, rows=5),
    ]
    p = predict.predict(prog, s=4, read_latency=3)
    assert p.cycles_total == 64
    assert p.cycles_dma == 7 + 8 + 21
    assert p.cycles_compute == 6 + 7
    assert p.macs_issued == 16 * 5
    assert [e.idle for e in p.timeline] == [12, 16, 25, 43]
    assert [(e.dma_start, e.feed_start) for e in p.timeline] == [
        (3, 11), (15, None), (None, 24), (42, None)]  # fmt: skip


def test_overlap_and_hazards() -> None:
    """M13: a LOAD_A into other rows starts while the COMPUTE streams; into the
    COMPUTE's rows it waits for the COMPUTE's done (WAR)."""
    s, lat = 4, 3
    base = [
        Command(op=OP_LOAD_W, mem_stride=4),
        Command(op=OP_LOAD_A, mem_stride=4, rows=20, buf_addr=0),
        Command(op=OP_COMPUTE, rows=20, buf_addr=0),
    ]
    other = predict.predict(base + [Command(op=OP_LOAD_A, mem_stride=4, rows=8, buf_addr=128)],
                            s=s, read_latency=lat).timeline  # fmt: skip
    same = predict.predict(base + [Command(op=OP_LOAD_A, mem_stride=4, rows=8, buf_addr=10)],
                           s=s, read_latency=lat).timeline  # fmt: skip
    comp = other[2]
    assert other[3].dma_start < comp.feed_done  # overlaps the COMPUTE
    assert same[3].dma_start == comp.feed_done + 1  # waits for the COMPUTE


def test_compute_after_compute_has_no_gap() -> None:
    """M13 accumulator tags: the second COMPUTE starts one cycle after the first's done."""
    prog = [
        Command(op=OP_LOAD_W, mem_stride=4),
        Command(op=OP_LOAD_A, mem_stride=4, rows=6),
        Command(op=OP_COMPUTE, rows=3, buf_addr=0),
        Command(op=OP_COMPUTE, rows=3, buf_addr=3, acc_addr=3),
    ]
    tl = predict.predict(prog, s=4, read_latency=3).timeline
    assert tl[3].feed_start == tl[2].feed_done + 1


def test_reload_gate_applies_after_compute() -> None:
    """LOAD_W right after COMPUTE: feeder start = max(DMA done + 1, COMPUTE done + 2S - 5)."""
    s, lat = 8, 1
    prog = [
        Command(op=OP_LOAD_W, mem_stride=8),
        Command(op=OP_LOAD_A, mem_stride=8, rows=1),
        Command(op=OP_COMPUTE, rows=1),
        Command(op=OP_LOAD_W, mem_stride=8),
    ]
    p = predict.predict(prog, s=s, read_latency=lat)
    compute_done = p.timeline[2].done
    w2 = p.timeline[3]
    assert w2.feed_start == max(w2.dma_done + 1, compute_done + 2 * s - 5)


def test_utilization_fields() -> None:
    a, b = np.ones((16, 8), dtype=np.int64), np.ones((8, 8), dtype=np.int64)
    prog = tiler.tile(a, b, s=8)
    p = predict.predict(prog.commands, s=8, read_latency=3, useful_macs=prog.stats.useful_macs)
    assert p.utilization == prog.stats.useful_macs / (64 * p.cycles_total)
    assert 0 < p.utilization < 1


def test_partial_load_w_reads_fewer_rows() -> None:
    full = predict.predict([Command(op=OP_LOAD_W, mem_stride=8)], s=8, read_latency=3)
    part = predict.predict([Command(op=OP_LOAD_W, mem_stride=8, rows=3)], s=8, read_latency=3)
    assert full.timeline[0].dma_done - part.timeline[0].dma_done == 8 - 3
