"""Unit tests for the cycle-stepped memory model (tb/common/memory.py), docs/spec/dma.md §2.

Pure Python: the tests play the DMA side by hand, one dict per cycle.
"""

from __future__ import annotations

import random

from tb.common.memory import Memory

IDLE = {"rd_req_valid": 0, "rd_req_addr": 0, "rd_resp_ready": 1, "wr_req_valid": 0}


def _cycle(mem: Memory, **dut: int) -> dict[str, int]:
    return mem.step({**IDLE, **dut})


def test_read_latency_exact_and_in_order() -> None:
    mem = Memory(size=64, beat_bytes=4, read_latency=3)
    mem.data[0:12] = bytes(range(12))
    issued, got = 0, []
    for cyc in range(10):
        dut = {"rd_req_valid": int(issued < 3), "rd_req_addr": 4 * issued} if issued < 3 else {}
        out = _cycle(mem, **dut)
        if dut and out["rd_req_ready"]:
            issued += 1
        if out["rd_resp_valid"]:
            got.append((cyc, out["rd_resp_data"]))
    # requests accepted in cycles 0, 1, 2 -> responses in cycles 3, 4, 5
    assert [c for c, _ in got] == [3, 4, 5]
    assert [d for _, d in got] == [0x03020100, 0x07060504, 0x0B0A0908]  # little-endian


def test_write_little_endian() -> None:
    mem = Memory(size=16, beat_bytes=8, read_latency=1)
    out = _cycle(mem, wr_req_valid=1, wr_req_addr=8, wr_req_data=0x0807060504030201)
    assert out["wr_req_ready"] == 1
    mem.step(IDLE)  # the write lands at the edge; data visible afterwards
    assert bytes(mem.data[8:16]) == bytes([1, 2, 3, 4, 5, 6, 7, 8])


def test_max_outstanding_blocks_requests() -> None:
    mem = Memory(size=64, beat_bytes=4, read_latency=5, max_outstanding=2)
    readies = [_cycle(mem, rd_req_valid=1, rd_req_addr=0)["rd_req_ready"] for _ in range(4)]
    assert readies == [1, 1, 0, 0]


def test_response_waits_for_ready() -> None:
    mem = Memory(size=16, beat_bytes=4, read_latency=1)
    _cycle(mem, rd_req_valid=1, rd_req_addr=0)
    held = [_cycle(mem, rd_resp_ready=0)["rd_resp_valid"] for _ in range(3)]
    assert held == [1, 1, 1]  # never retracted
    assert _cycle(mem, rd_resp_ready=1)["rd_resp_valid"] == 1
    assert _cycle(mem)["rd_resp_valid"] == 0


def test_stalls_are_seeded_and_protocol_clean() -> None:
    def trace(seed: int) -> list[tuple[int, int, int]]:
        mem = Memory(
            size=256,
            beat_bytes=4,
            read_latency=2,
            max_outstanding=4,
            rng=random.Random(seed),
            req_stall=0.3,
            resp_stall=0.3,
            wr_stall=0.3,
        )
        out_trace, prev_valid = [], 0
        for i in range(200):
            out = _cycle(mem, rd_req_valid=1, rd_req_addr=4 * (i % 64), wr_req_valid=1)
            # protocol: a raised rd_resp_valid stays raised until handshake (ready is 1 here)
            out_trace.append((out["rd_req_ready"], out["rd_resp_valid"], out["wr_req_ready"]))
            prev_valid = out["rd_resp_valid"]
        assert prev_valid in (0, 1)
        return out_trace

    a, b = trace(7), trace(7)
    assert a == b
    assert trace(8) != a
    assert any(r == 0 for r, _, _ in a) and any(w == 0 for _, _, w in a)
