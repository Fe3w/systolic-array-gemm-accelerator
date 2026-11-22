"""Tiling compiler: C = A @ B for any M, N, K onto sa_top commands (BRIEF §7, M9).

Memory image (the host prepares it): zero-padded copies of A (M x Kp int8) and
B (Kp x Np int8), Kp and Np rounded up to multiples of S, and room for C_pad
(M x Np int32, little-endian); C = C_pad[:, :N]. Padded MACs are issued but
not useful (BRIEF §9.1).

Orders (BRIEF §7.2):
  A (weight reuse): for each block of <= 256 rows (accumulator depth):
       for n_t: for k_t: LOAD_W; for each m_c chunk: LOAD_A; COMPUTE -> acc rows
       then STORE the block's rows of this column strip.
  B (output tile first): for each m_c chunk: for n_t: for k_t: LOAD_W; LOAD_A; COMPUTE
       then STORE the chunk.
Double buffering (M13): the default chunk is m_c = min(M, 128) and LOAD_As
alternate between the input-buffer halves 0..127 and 128..255 (ping-pong), so
the next chunk's LOAD_A can run on the DMA while the feeder streams the current
one. After generation each LOAD_A is moved ahead of any LOAD_W / STORE directly
before it (they touch other storage, so the program's result is unchanged); its
transfer then overlaps the previous COMPUTE instead of queueing behind the
weight reload or the STORE's drain wait.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from sysarray.commands import (
    ACCUMULATE,
    DEPTH,
    OP_COMPUTE,
    OP_LOAD_A,
    OP_LOAD_W,
    OP_STORE,
    OVERWRITE,
    Command,
)

ALIGN = 64


def _ceil_to(x: int, m: int) -> int:
    return -(-x // m) * m


@dataclass
class Stats:
    s: int
    m: int
    n: int
    k: int
    kp: int
    np_: int
    order: str
    m_c: int
    weight_bytes: int = 0
    act_bytes: int = 0
    out_bytes: int = 0
    n_commands: int = 0
    useful_macs: int = 0
    issued_macs: int = 0


@dataclass
class Program:
    s: int
    commands: list[Command]
    image: list[tuple[int, bytes]]
    mem_size: int
    c_base: int
    m: int
    n: int
    np_: int
    stats: Stats
    meta: dict = field(default_factory=dict)

    def read_c(self, mem: bytearray) -> np.ndarray:
        raw = bytes(mem[self.c_base : self.c_base + 4 * self.m * self.np_])
        return np.frombuffer(raw, dtype="<i4").reshape(self.m, self.np_)[:, : self.n].copy()


def _chunks(start: int, stop: int, size: int) -> Iterator[tuple[int, int]]:
    for lo in range(start, stop, size):
        yield lo, min(size, stop - lo)


def _hoist_load_a(cmds: list[Command]) -> list[Command]:
    """Move every LOAD_A ahead of the LOAD_W / STORE commands directly before it."""
    out: list[Command] = []
    for c in cmds:
        if c.op == OP_LOAD_A:
            i = len(out)
            while i > 0 and out[i - 1].op in (OP_LOAD_W, OP_STORE):
                i -= 1
            out.insert(i, c)
        else:
            out.append(c)
    return out


def tile(a: np.ndarray, b: np.ndarray, s: int, order: str = "A", m_c: int | None = None) -> Program:
    a, b = np.asarray(a), np.asarray(b)
    m, k = a.shape
    k2, n = b.shape
    if k != k2:
        raise ValueError(f"inner dimensions differ: {a.shape} x {b.shape}")
    if order not in ("A", "B"):
        raise ValueError(f"unknown order {order!r}; use 'A' or 'B'")
    m_c = min(m, DEPTH // 2) if m_c is None else m_c
    if not 1 <= m_c <= DEPTH:
        raise ValueError(f"m_c={m_c} must be in 1..{DEPTH}")
    kp, np_ = _ceil_to(k, s), _ceil_to(n, s)

    a_pad = np.zeros((m, kp), dtype=np.int8)
    a_pad[:, :k] = a
    b_pad = np.zeros((kp, np_), dtype=np.int8)
    b_pad[:k, :n] = b
    a_base = 0
    b_base = _ceil_to(a_base + a_pad.size, ALIGN)
    c_base = _ceil_to(b_base + b_pad.size, ALIGN)
    mem_size = _ceil_to(c_base + 4 * m * np_, ALIGN)

    st = Stats(s=s, m=m, n=n, k=k, kp=kp, np_=np_, order=order, m_c=m_c, useful_macs=m * n * k)
    cmds: list[Command] = []

    def load_w(k_t: int, n_t: int) -> None:
        # Only real rows of B are read; the last k-tile of a K that is not a multiple
        # of S has K % S of them (rows = 0 means a full tile; M11b, issue 7).
        real = min(s, k - k_t * s)
        cmds.append(Command(op=OP_LOAD_W, mem_addr=b_base + k_t * s * np_ + n_t * s,
                            mem_stride=np_, rows=0 if real == s else real))  # fmt: skip
        st.weight_bytes += s * real

    ping_pong = m_c <= DEPTH // 2
    half = [0]  # input-buffer half of the latest LOAD_A

    def load_a(m0: int, rows: int, k_t: int) -> None:
        cmds.append(Command(op=OP_LOAD_A, mem_addr=a_base + m0 * kp + k_t * s, mem_stride=kp,
                            rows=rows, buf_addr=half[0] * (DEPTH // 2)))  # fmt: skip
        st.act_bytes += rows * s

    def compute(rows: int, acc_addr: int, k_t: int) -> None:
        mode = OVERWRITE if k_t == 0 else ACCUMULATE
        cmds.append(Command(op=OP_COMPUTE, acc_mode=mode, rows=rows,
                            buf_addr=half[0] * (DEPTH // 2), acc_addr=acc_addr))  # fmt: skip
        if ping_pong:
            half[0] ^= 1
        st.issued_macs += s * s * rows

    def store(m0: int, rows: int, n_t: int, acc_addr: int) -> None:
        cmds.append(Command(op=OP_STORE, mem_addr=c_base + 4 * (m0 * np_ + n_t * s),
                            mem_stride=4 * np_, rows=rows, buf_addr=acc_addr))  # fmt: skip
        st.out_bytes += rows * s * 4

    n_tiles, k_tiles = np_ // s, kp // s
    if order == "A":
        for blk0, blk_rows in _chunks(0, m, DEPTH):
            for n_t in range(n_tiles):
                for k_t in range(k_tiles):
                    load_w(k_t, n_t)
                    for m0, rows in _chunks(blk0, blk0 + blk_rows, m_c):
                        load_a(m0, rows, k_t)
                        compute(rows, m0 - blk0, k_t)
                store(blk0, blk_rows, n_t, 0)
    else:
        for m0, rows in _chunks(0, m, m_c):
            for n_t in range(n_tiles):
                for k_t in range(k_tiles):
                    load_w(k_t, n_t)
                    load_a(m0, rows, k_t)
                    compute(rows, 0, k_t)
                store(m0, rows, n_t, 0)
    cmds = _hoist_load_a(cmds)
    st.n_commands = len(cmds)
    image = [(a_base, a_pad.tobytes()), (b_base, b_pad.tobytes())]
    return Program(s=s, commands=cmds, image=image, mem_size=mem_size, c_base=c_base, m=m, n=n,
                   np_=np_, stats=st)  # fmt: skip
