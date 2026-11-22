#!/usr/bin/env python3
"""Group the max-slew violations of a LibreLane run by driver cell and source signal (M12b).

Reads the final gate-level netlist and one corner's post-route `checks.rpt`
(the "max slew" table), maps every violating pin to its net, finds the cell that
drives that net, and walks back through buffers to the register or port the
signal comes from. Prints per-corner counts, the driver cell types and the
source groups (indices folded, e.g. `u_pe.w_ext[i]`).

Usage: python3 scripts/librelane/slew_diag.py <run_dir>   (e.g. build/asic/<name>/runs/run)
"""

from __future__ import annotations

import collections
import re
import statistics
import sys
from pathlib import Path

OUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
BUFFER = re.compile(r"__(buf|clkbuf|dlygate|clkdlybuf)")
INST = re.compile(r"^\s*(sky130_\w+)\s+(\S+)\s*\((.*?)\);", re.S | re.M)
VIOL = re.compile(r"^(\S+)/(\w+)\s+[\d.]+\s+([\d.]+)\s+-[\d.]+ \(VIOLATED\)", re.M)


def parse_netlist(text: str) -> tuple[dict, dict, dict, dict]:
    pin_net: dict[tuple[str, str], str] = {}
    drivers: dict[str, tuple[str, str]] = {}
    loads: dict[str, list] = collections.defaultdict(list)
    cell_of: dict[str, str] = {}
    for m in INST.finditer(text):
        cell, inst, body = m.groups()
        inst = inst.lstrip("\\")
        cell_of[inst] = cell
        for pin, net in re.findall(r"\.(\w+)\(([^()]*)\)", body):
            net = net.strip().lstrip("\\").strip()
            if not net:
                continue
            pin_net[(inst, pin)] = net
            (drivers.__setitem__(net, (inst, pin)) if pin in OUT_PINS
             else loads[net].append((inst, pin)))  # fmt: skip
    return pin_net, drivers, loads, cell_of


def slew_table(report: str) -> list[tuple[str, str, float]]:
    sec = report[report.index("\nmax slew"):]
    ends = [i for i in (sec.find("\nmax fanout"), sec.find("\nmax capacitance"),
                        sec.find("max slew violation count")) if i > 0]  # fmt: skip
    sec = sec[: min(ends)]
    return [(i.lstrip("\\"), p, float(s)) for i, p, s in VIOL.findall(sec)]


def fold(name: str) -> str:
    name = re.sub(r"\[\d+\]", "[i]", name)
    return re.sub(r"\d+", "N", name) if name.startswith("_") else name


def source(net: str, drivers: dict, cell_of: dict, pin_net: dict) -> str:
    for _ in range(16):
        if net not in drivers:
            return net  # a port
        inst, _pin = drivers[net]
        if not BUFFER.search(cell_of[inst]):
            return net  # a register or logic output
        net = pin_net.get((inst, "A"), net)
    return net


def main() -> int:
    run = Path(sys.argv[1])
    pin_net, drivers, loads, cell_of = parse_netlist(next(run.glob("final/nl/*.nl.v")).read_text())
    sta = sorted(run.glob("*-openroad-stapostpnr"))[-1]
    for corner in sorted(p.name for p in sta.iterdir() if (p / "checks.rpt").exists()):
        m = re.search(r"max slew violation count (\d+)", (sta / corner / "checks.rpt").read_text())
        print(f"{corner:20s} max-slew violations {m.group(1) if m else 0}")
    worst = max((p for p in sta.iterdir() if (p / "checks.rpt").exists()),
                key=lambda p: len(slew_table((p / "checks.rpt").read_text())))  # fmt: skip
    viol = slew_table((worst / "checks.rpt").read_text())
    by_net: dict[str, list[float]] = collections.defaultdict(list)
    for inst, pin, slew in viol:
        by_net[pin_net.get((inst, pin), "?")].append(slew)
    print(f"\ncorner {worst.name}: {len(viol)} violating pins on {len(by_net)} nets")
    drv = collections.Counter()
    groups: dict[str, list] = collections.defaultdict(list)
    for net, slews in by_net.items():
        cell = cell_of.get(drivers.get(net, ("", ""))[0], "port").replace("sky130_fd_sc_hd__", "")
        drv[cell] += len(slews)
        groups[fold(source(net, drivers, cell_of, pin_net))].append(
            (len(slews), len(loads.get(net, [])), max(slews)))
    print("\nviolating pins by driver cell:")
    for cell, n in drv.most_common(8):
        print(f"{n:7d}  {cell}")
    print("\nviolating pins by source signal: pins, nets, fanout median/max, worst slew (ns)")
    for key, v in sorted(groups.items(), key=lambda kv: -sum(x[0] for x in kv[1]))[:12]:
        fo = [x[1] for x in v]
        print(f"{sum(x[0] for x in v):7d} {len(v):5d}  {statistics.median(fo):4.0f} {max(fo):4d}  "
              f"{max(x[2] for x in v):.3f}  {key}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
