"""Functional simulator of the sa_top command semantics (docs/spec/ctrl.md §1).

No timing: commands run in program order on a bytearray memory. Used by the
compiler's unit tests and by the RTL testbenches as the reference model.
Reading an input-buffer or accumulator row that was never written raises
KeyError, which catches compiler bugs that the RTL would silently accept.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from sysarray.commands import ACCUMULATE, OP_COMPUTE, OP_LOAD_A, OP_LOAD_W, OP_STORE, Command
from sysarray.golden import to_int32


class Machine:
    def __init__(self, mem: bytearray, s: int) -> None:
        self.mem, self.s = mem, s
        self.weights: np.ndarray | None = None
        self.ibuf: dict[int, np.ndarray] = {}
        self.acc: dict[int, np.ndarray] = {}

    def _row8(self, addr: int) -> np.ndarray:
        raw = bytes(self.mem[addr : addr + self.s])
        return np.frombuffer(raw, dtype=np.int8).astype(np.int64)

    def run(self, c: Command) -> None:
        s = self.s
        if c.op == OP_LOAD_W:
            # rows = number of real weight rows (0 means S, M11b); the rest are zero.
            real = s if c.rows == 0 else c.rows
            self.weights = np.stack(
                [self._row8(c.mem_addr + r * c.mem_stride) if r < real else np.zeros(s, np.int64)
                 for r in range(s)]
            )  # fmt: skip
        elif c.op == OP_LOAD_A:
            for i in range(c.rows):
                self.ibuf[c.buf_addr + i] = self._row8(c.mem_addr + i * c.mem_stride)
        elif c.op == OP_COMPUTE:
            if self.weights is None:
                raise RuntimeError("COMPUTE before LOAD_W")
            for i in range(c.rows):
                prod = self.ibuf[c.buf_addr + i] @ self.weights
                old = self.acc[c.acc_addr + i] if c.acc_mode == ACCUMULATE else 0
                self.acc[c.acc_addr + i] = to_int32(old + prod).astype(np.int64)
        elif c.op == OP_STORE:
            for i in range(c.rows):
                addr = c.mem_addr + i * c.mem_stride
                self.mem[addr : addr + 4 * s] = self.acc[c.buf_addr + i].astype("<i4").tobytes()
        else:
            raise ValueError(f"unknown op {c.op}")


def execute(commands: Iterable[Command], mem: bytearray, s: int) -> Machine:
    machine = Machine(mem, s)
    for c in commands:
        machine.run(c)
    return machine
