"""Tests for the compile CLI (python3 -m sysarray.cli)."""

from __future__ import annotations

import json
from pathlib import Path

from sysarray import cli
from sysarray.commands import Command


def test_cli_writes_program(tmp_path: Path) -> None:
    out = tmp_path / "prog.json"
    assert cli.main(["13", "9", "11", "--S", "4", "--order", "B", "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert (d["M"], d["N"], d["K"], d["S"], d["order"]) == (13, 9, 11, 4, "B")
    cmds = [Command.decode(int(h, 16)) for h in d["commands_hex"]]
    assert len(cmds) == d["stats"]["n_commands"] > 0
    assert d["predicted"]["label"] == "predicted (analytical)"
    assert d["predicted"]["cycles_total"] > 0
