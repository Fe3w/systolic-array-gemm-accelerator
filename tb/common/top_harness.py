"""Shared per-cycle harness for sa_top testbenches (tb/top, tb/gemm).

Each tick (falling edge): step the memory model with the DUT's request
channels, drive memory outputs, the next queued command (when any) and extra
inputs, wait 1 ns, sample status. Tracks accepts, unit busy cycles and the
last STORE's DMA done for the counter cross-checks of docs/spec/ctrl.md §4.
"""

from __future__ import annotations

import random

from cocotb.triggers import FallingEdge, Timer

from sysarray.commands import Command
from tb.common.memory import Memory
from tb.common.utils import reset_sync

MEM_SIZE = 1 << 16
TOP_INPUTS = ("cmd_valid", "cmd", "err_clear", "rd_req_ready", "rd_resp_valid", "rd_resp_data",
              "wr_req_ready")  # fmt: skip


def _u(sig) -> int:
    v = sig.value
    return v.to_unsigned() if hasattr(v, "to_unsigned") else int(v)


class Top:
    """Per-cycle driver: memory model, command queue, counter bookkeeping."""

    def __init__(self, dut, mem: Memory, s: int) -> None:
        self.dut, self.mem, self.s = dut, mem, s
        self.cycle = 0
        self.queue: list[Command] = []
        self.accepted: list[tuple[int, Command]] = []
        self.first_accept: int | None = None
        self.last_store_done: int | None = None
        self.dma_busy_cycles = 0
        self.feed_busy_cycles = 0
        self.events: list[tuple[int, str]] = []
        self.dma_is_store = False

    async def tick(self, **inputs: int) -> dict[str, int]:
        d = self.dut
        await FallingEdge(d.clk)
        out = self.mem.step({
            "rd_req_valid": _u(d.rd_req_valid), "rd_req_addr": _u(d.rd_req_addr),
            "rd_resp_ready": _u(d.rd_resp_ready), "wr_req_valid": _u(d.wr_req_valid),
            "wr_req_addr": _u(d.wr_req_addr), "wr_req_data": _u(d.wr_req_data)})  # fmt: skip
        ready = _u(d.cmd_ready)
        drive = {"cmd_valid": 0, "cmd": 0, "err_clear": 0, **inputs, **out}
        if self.queue and "cmd_valid" not in inputs:
            drive["cmd_valid"], drive["cmd"] = 1, self.queue[0].encode()
            if ready:  # handshake at the coming rising edge
                cmd = self.queue.pop(0)
                self.accepted.append((self.cycle, cmd))
                if self.first_accept is None:
                    self.first_accept = self.cycle
        for k, v in drive.items():
            getattr(d, k).value = v
        await Timer(1, unit="ns")
        core = d.u_core
        st = {"cycle": self.cycle, "ready": ready, "busy": _u(d.busy), "err": _u(d.err),
              "err_code": _u(d.err_code), "dma_start": _u(core.dma_start),
              "f_start": _u(core.f_start), "dma_done": _u(core.dma_done),
              "f_done": _u(core.f_done)}  # fmt: skip
        st["dma_busy"], st["f_busy"] = _u(core.dma_busy), _u(core.f_busy)
        self.dma_busy_cycles += st["dma_busy"]
        self.feed_busy_cycles += st["f_busy"]
        # M13: commands overlap, so the running DMA transfer is not necessarily the
        # last accepted command; remember the direction at its start instead.
        if st["dma_start"]:
            self.dma_is_store = _u(core.dma_dir) == 1
        if st["dma_done"] and self.dma_is_store:
            self.last_store_done = self.cycle
        for name in ("dma_start", "f_start", "dma_done", "f_done"):
            if st[name]:
                self.events.append((self.cycle, name))
        self.cycle += 1
        return st

    async def run_all(self, max_cycles: int = 400000) -> None:
        """Issue every queued command and wait until the controller is idle again."""
        for _ in range(max_cycles):
            st = await self.tick()
            # The tick that pops the last command still sees ready = 1 / busy = 0
            # (its handshake happens at the next edge), so require a later cycle.
            last_accept = self.accepted[-1][0] if self.accepted else -1
            if not self.queue and st["cycle"] > last_accept and st["ready"] and not st["busy"]:
                await self.tick()
                return
        raise AssertionError("commands did not finish (hang?)")


async def reset_top(dut) -> None:
    """Idle inputs and a synchronous reset (the clock must already run)."""
    for name in TOP_INPUTS:
        getattr(dut, name).value = 0
    await reset_sync(dut.clk, dut.rst, cycles=2)


def make_memory(
    s: int, rng, stalls: float, latency: int = 3, max_outstanding: int = 4, size: int = MEM_SIZE
) -> Memory:
    return Memory(size, s, read_latency=latency, max_outstanding=max_outstanding,
                  rng=random.Random(rng.getrandbits(32)), req_stall=stalls,
                  resp_stall=stalls, wr_stall=stalls)  # fmt: skip
