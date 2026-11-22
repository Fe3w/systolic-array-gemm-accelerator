"""Cycle-stepped, byte-addressable memory model behind valid/ready channels (docs/spec/dma.md §2).

The model is pure Python: ``step()`` takes the DUT's outputs for one cycle and
returns the memory's outputs for the same cycle. The handshakes agreed in that
cycle take effect "at the edge", i.e. inside the same ``step()`` call after the
outputs are decided. A cocotb driver calls ``step()`` once per falling edge.
"""

from __future__ import annotations

import random
from collections import deque


class Memory:
    def __init__(
        self,
        size: int,
        beat_bytes: int,
        read_latency: int = 1,
        max_outstanding: int = 1 << 30,
        rng: random.Random | None = None,
        req_stall: float = 0.0,
        resp_stall: float = 0.0,
        wr_stall: float = 0.0,
    ) -> None:
        if read_latency < 1:
            raise ValueError("read_latency must be >= 1")
        self.data = bytearray(size)
        self.beat_bytes = beat_bytes
        self.read_latency = read_latency
        self.max_outstanding = max_outstanding
        self.rng = rng or random.Random(0)
        self.req_stall, self.resp_stall, self.wr_stall = req_stall, resp_stall, wr_stall
        self.cycle = 0
        self.pending: deque[tuple[int, int]] = deque()  # (eligible cycle, address), in order
        self.resp_raised = False  # rd_resp_valid already shown for pending[0]
        self.reads = 0
        self.writes = 0

    def _check_addr(self, addr: int) -> None:
        if addr % self.beat_bytes or not 0 <= addr <= len(self.data) - self.beat_bytes:
            raise ValueError(f"bad beat address {addr:#x}")

    def read_beat(self, addr: int) -> int:
        self._check_addr(addr)
        return int.from_bytes(self.data[addr : addr + self.beat_bytes], "little")

    def write_beat(self, addr: int, value: int) -> None:
        self._check_addr(addr)
        self.data[addr : addr + self.beat_bytes] = value.to_bytes(self.beat_bytes, "little")

    def step(self, dut: dict[str, int]) -> dict[str, int]:
        """One cycle. ``dut`` holds rd_req_valid/addr, rd_resp_ready, wr_req_valid/addr/data."""
        # Decide this cycle's outputs (they may depend on the DUT's valids; the DUT's
        # valids must not depend on them, which is the DUT's obligation).
        rd_req_ready = int(
            len(self.pending) < self.max_outstanding and self.rng.random() >= self.req_stall
        )
        wr_req_ready = int(self.rng.random() >= self.wr_stall)
        rd_resp_valid, rd_resp_data = 0, 0
        if self.pending and self.pending[0][0] <= self.cycle:
            if self.resp_raised or self.rng.random() >= self.resp_stall:
                rd_resp_valid = 1
                rd_resp_data = self.read_beat(self.pending[0][1])
                self.resp_raised = True

        # Edge: perform the handshakes.
        if rd_resp_valid and dut.get("rd_resp_ready", 0):
            self.pending.popleft()
            self.resp_raised = False
        if dut.get("rd_req_valid", 0) and rd_req_ready:
            addr = dut["rd_req_addr"]
            self._check_addr(addr)
            self.pending.append((self.cycle + self.read_latency, addr))
            self.reads += 1
        if dut.get("wr_req_valid", 0) and wr_req_ready and "wr_req_addr" in dut:
            self.write_beat(dut["wr_req_addr"], dut["wr_req_data"])
            self.writes += 1

        self.cycle += 1
        return {
            "rd_req_ready": rd_req_ready,
            "rd_resp_valid": rd_resp_valid,
            "rd_resp_data": rd_resp_data,
            "wr_req_ready": wr_req_ready,
        }
