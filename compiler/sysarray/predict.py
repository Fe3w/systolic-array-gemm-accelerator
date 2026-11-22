"""Cycle predictor for sa_top command programs (M9, M13). Predicted (analytical).

Replays the controller timing of docs/spec/ctrl.md §2-§3 for a memory that
accepts one read request per cycle with a fixed read latency L and never
stalls (the predictor's assumption; with stalls the hardware is slower).

M13 in-order dispatcher with concurrent DMA and feeder: accept in cycle t,
CHECK in t + 1, DECIDE in t + 2 (M11c), unit start in the first u >= t + 3
where the unit is free (one cycle after its last done) and the command's
dependencies on the other unit's in-flight work are clear (that work's done + 1):
  LOAD_A  : WAR with a COMPUTE reading overlapping input rows
  STORE   : any COMPUTE in flight; and u >= last COMPUTE done + 2S + 3
  LOAD_W  : a LOAD_W still on the feeder; then feeder start v >= max(DMA done + 1,
            feeder free, last COMPUTE done + max(0, 2S - 5))
  COMPUTE : RAW with a LOAD_A writing overlapping input rows; a STORE in flight
Durations: LOAD_A R rows: DMA done u + R + L; LOAD_W: DMA done u + rows + L,
feeder done v + S + 2; COMPUTE R rows: done u + R + 2; STORE R rows: done u + 4R + 1.
Next accept: u + 1 (LOAD_W: v + 1). Counters (spec §4): busy cycles of a unit =
done - start; cycles_total = last STORE done - first accept + 1.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sysarray.commands import OP_COMPUTE, OP_LOAD_A, OP_LOAD_W, OP_STORE, Command


@dataclass
class Event:
    op: int
    accept: int
    dma_start: int | None = None
    dma_done: int | None = None
    feed_start: int | None = None
    feed_done: int | None = None
    done: int = 0
    idle: int = 0


@dataclass
class Prediction:
    cycles_total: int
    cycles_dma: int
    cycles_compute: int
    macs_issued: int
    utilization: float | None
    timeline: list[Event] = field(default_factory=list)


def _overlap(lo1: int, rows1: int, lo2: int, rows2: int) -> bool:
    return lo1 < lo2 + rows2 and lo2 < lo1 + rows1


def predict(
    commands: Iterable[Command], s: int, read_latency: int, useful_macs: int | None = None
) -> Prediction:
    t = 0  # accept cycle of the next command
    reload_ok = store_ok = 0
    dma_free = f_free = 0  # first cycle each unit is free
    dma_cur: Command | None = None  # last command started on the DMA (in flight until dma_free)
    f_cur: Command | None = None  # last command started on the feeder
    dma = comp = macs = 0
    first_accept, last_store_done = 0, None
    timeline: list[Event] = []
    for c in commands:
        e = Event(op=c.op, accept=t)
        u = t + 3  # CHECK in t + 1, DECIDE in t + 2 (M11c, D-028)
        f_comp = f_cur is not None and f_cur.op == OP_COMPUTE
        if c.op == OP_LOAD_A:
            u = max(u, dma_free)
            if f_comp and _overlap(c.buf_addr, c.rows, f_cur.buf_addr, f_cur.rows):
                u = max(u, f_free)
            e.dma_start, e.dma_done = u, u + c.rows + read_latency
            e.done, e.idle = e.dma_done, u + 1
        elif c.op == OP_STORE:
            u = max(u, dma_free, store_ok, f_free if f_comp else 0)
            e.dma_start, e.dma_done = u, u + 4 * c.rows + 1
            e.done, e.idle = e.dma_done, u + 1
            last_store_done = e.done
        elif c.op == OP_LOAD_W:
            real = s if c.rows == 0 else c.rows  # M11b: partial weight tiles
            u = max(u, dma_free, f_free if (f_cur is not None and not f_comp) else 0)
            e.dma_start, e.dma_done = u, u + real + read_latency
            e.feed_start = max(e.dma_done + 1, f_free, reload_ok)
            e.feed_done = e.feed_start + s + 2
            e.done, e.idle = e.feed_done, e.feed_start + 1
        elif c.op == OP_COMPUTE:
            u = max(u, f_free)
            if dma_cur is not None and (
                dma_cur.op == OP_STORE
                or (dma_cur.op == OP_LOAD_A
                    and _overlap(c.buf_addr, c.rows, dma_cur.buf_addr, dma_cur.rows))
            ):  # fmt: skip
                u = max(u, dma_free)
            e.feed_start, e.feed_done = u, u + c.rows + 2
            e.done, e.idle = e.feed_done, u + 1
            reload_ok = e.done + max(0, 2 * s - 5)
            store_ok = e.done + 2 * s + 3
            macs += s * s * c.rows
        else:
            raise ValueError(f"unknown op {c.op}")
        if e.dma_start is not None:
            dma += e.dma_done - e.dma_start
            dma_free, dma_cur = e.dma_done + 1, c
        if e.feed_start is not None:
            comp += e.feed_done - e.feed_start
            f_free, f_cur = e.feed_done + 1, c
        timeline.append(e)
        t = e.idle
    total = 0 if last_store_done is None else last_store_done - first_accept + 1
    util = None
    if useful_macs is not None and total:
        util = useful_macs / (s * s * total)
    return Prediction(cycles_total=total, cycles_dma=dma, cycles_compute=comp, macs_issued=macs,
                      utilization=util, timeline=timeline)  # fmt: skip
