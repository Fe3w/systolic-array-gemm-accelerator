"""Command format for sa_top, mirroring rtl/ctrl/sa_pkg.sv (docs/spec/ctrl.md §1, D-021).

A command is one 93-bit word; fields are packed MSB first exactly like the SV
`cmd_t` packed struct. compiler/tests/test_commands.py checks the two agree.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

OP_LOAD_W, OP_LOAD_A, OP_COMPUTE, OP_STORE = 0, 1, 2, 3
OVERWRITE, ACCUMULATE = 0, 1
DEPTH = 256

# (name, width) MSB first, identical to sa_pkg::cmd_t.
FIELDS: tuple[tuple[str, int], ...] = (
    ("op", 3),
    ("acc_mode", 1),
    ("mem_addr", 32),
    ("mem_stride", 32),
    ("rows", 9),
    ("buf_addr", 8),
    ("acc_addr", 8),
)
CMD_W = sum(w for _, w in FIELDS)


@dataclass(frozen=True)
class Command:
    op: int
    acc_mode: int = 0
    mem_addr: int = 0
    mem_stride: int = 0
    rows: int = 0
    buf_addr: int = 0
    acc_addr: int = 0

    def encode(self) -> int:
        word = 0
        for name, width in FIELDS:
            value = getattr(self, name)
            if not 0 <= value < (1 << width):
                raise ValueError(f"{name}={value} does not fit in {width} bits")
            word = (word << width) | value
        return word

    @classmethod
    def decode(cls, word: int) -> Command:
        values = {}
        for name, width in reversed(FIELDS):
            values[name] = word & ((1 << width) - 1)
            word >>= width
        return cls(**values)


assert [f.name for f in fields(Command)] == [n for n, _ in FIELDS]
