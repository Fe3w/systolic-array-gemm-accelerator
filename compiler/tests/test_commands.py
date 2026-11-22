"""Tests for sysarray.commands, the Python mirror of rtl/ctrl/sa_pkg.sv (D-021)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sysarray import commands as cmds

PKG = Path(__file__).resolve().parents[2] / "rtl" / "ctrl" / "sa_pkg.sv"


def _pkg_fields() -> list[tuple[str, int]]:
    """Field names and widths of cmd_t, MSB first, parsed from the SV package."""
    text = PKG.read_text()
    body = re.search(r"typedef struct packed \{(.*?)\}\s*cmd_t;", text, re.S).group(1)
    consts = {m[0]: int(m[1]) for m in re.findall(r"localparam int (\w+)\s*=\s*(\d+);", text)}
    fields = []
    for line in body.splitlines():
        line = line.split("//")[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"(logic|op_t)\s*(?:\[(\w+)-1:0\])?\s*(\w+);", line)
        assert m, f"unparsed struct line: {line!r}"
        kind, width_const, name = m.groups()
        if kind == "op_t":
            width = consts["OP_W"]
        else:
            width = consts[width_const] if width_const else 1
        fields.append((name, width))
    return fields


def test_mirror_matches_sv_package() -> None:
    assert _pkg_fields() == list(cmds.FIELDS)
    assert cmds.CMD_W == sum(w for _, w in cmds.FIELDS) == 93


def test_opcodes_match_package() -> None:
    text = PKG.read_text()
    for name, value in (("OP_LOAD_W", 0), ("OP_LOAD_A", 1), ("OP_COMPUTE", 2), ("OP_STORE", 3)):
        assert re.search(rf"{name}\s*=\s*3'd{value}", text), name
        assert getattr(cmds, name) == value


def test_encode_decode_roundtrip() -> None:
    c = cmds.Command(op=cmds.OP_COMPUTE, acc_mode=1, mem_addr=0xDEADBEEF, mem_stride=0x40,
                     rows=256, buf_addr=255, acc_addr=7)  # fmt: skip
    word = c.encode()
    assert word >> (cmds.CMD_W - 3) == cmds.OP_COMPUTE  # op is the MSB field
    assert word & 0xFF == 7  # acc_addr is the LSB field
    assert cmds.Command.decode(word) == c


def test_field_range_checked() -> None:
    with pytest.raises(ValueError, match="rows"):
        cmds.Command(op=cmds.OP_LOAD_A, rows=512).encode()
    with pytest.raises(ValueError, match="mem_addr"):
        cmds.Command(op=cmds.OP_LOAD_A, mem_addr=-1).encode()
