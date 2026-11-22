#!/usr/bin/env python3
"""Cycle table from an sa_array VCD, sampled once per cycle (after the falling-edge drive).

Usage: python3 scripts/waves/vcd_cycle_table.py <dump.vcd> <pulse index>
Prints a_valid, grid_a_valid, grid_valid, c_valid for 9 cycles from the N-th isolated
a_valid pulse. Produce the VCD with: SYSARRAY_WAVES=1 make test-rtl (M3 cycle log).

Sampling note: at a falling-edge timestamp the VCD lists clk before the inputs cocotb
drives at that edge, so each sample is taken at the end of that timestamp. A row then
shows the inputs of cycle k with the registered outputs visible in cycle k, the
numbering of docs/spec/array.md and tb.common.utils.drive_cycles.
"""

import sys

path, which = sys.argv[1], int(sys.argv[2])
want = {"clk", "a_valid", "w_load", "grid_a_valid", "grid_valid", "c_valid"}
ids, scope, cur, samples, pending = {}, [], {}, [], False
with open(path) as f:
    for line in f:
        s = line.strip()
        if s.startswith("$scope"):
            scope.append(s.split()[2])
        elif s.startswith("$upscope"):
            scope.pop()
        elif s.startswith("$var"):
            p = s.split()
            if scope == ["sa_array"] and p[4] in want:
                ids[p[3]] = p[4]
        elif s.startswith("#"):
            if pending:  # end of the timestamp in which clk fell: inputs driven now included
                samples.append(dict(cur))
                pending = False
        elif s and s[0] in "01xz" and s[1:] in ids:
            name = ids[s[1:]]
            if name == "clk" and cur.get("clk") == "1" and s[0] == "0":
                pending = True
            cur[name] = s[0]
        elif s.startswith("b"):
            v, code = s[1:].split()
            if code in ids:
                cur[ids[code]] = v
av = [x.get("a_valid") == "1" for x in samples]
pulses = [k for k in range(1, len(av) - 1) if av[k] and not av[k - 1] and not av[k + 1]]
t0 = pulses[which]
print(f"isolated a_valid pulse #{which} at falling-edge sample {t0}; table relative to t0")
print("cyc  a_valid  grid_a_valid[3:0]  grid_valid[3:0]  c_valid")
for k in range(t0, t0 + 9):
    x = samples[k]
    gav, gv = x["grid_a_valid"].zfill(4), x["grid_valid"].zfill(4)
    print(f"t0+{k - t0:<2} {x['a_valid']:>5}  {gav:>17}  {gv:>15}  {x['c_valid']:>7}")
