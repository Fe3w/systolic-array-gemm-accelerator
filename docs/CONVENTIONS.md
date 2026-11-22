# Engineering rules and conventions

The rules every change in this repository follows. Code comments and
`docs/DECISIONS.md` refer to them by number ("rule 8").

## Rules

1. **Synthesizable SystemVerilog only.** `always_ff` / `always_comb`, `logic`,
   explicit widths, explicit `signed`. No latches, no multiple drivers, no
   combinational loops, no `#` delays, no `initial` blocks in synthesizable RTL.
   Every module starts with `` `default_nettype none `` and ends with
   `` `default_nettype wire ``. Reset style: `docs/DECISIONS.md` D-005.
2. **Test first.** Every RTL change gets a cocotb test written (or extended)
   before the RTL; where feasible the test is shown failing before the change
   and passing after.
3. **NumPy is the golden reference.** RTL results are compared against
   `compiler/sysarray/golden.py`, which is itself unit-tested against plain
   NumPy.
4. **Never invent numbers.** Every cycle count, utilization, LUT, DSP, Fmax,
   area or slack in the docs comes from a file in `results/` produced by a
   script in this repository, and the file is cited next to the number.
   Analytical predictions are labelled "predicted (analytical)" and shown with
   their formula and assumptions.
5. **Reason in cycles.** Timing changes (skew, de-skew, pipelines, handshakes,
   FSMs) come with a cycle-by-cycle table in the spec: fill latency, drain
   latency, steady-state throughput.
6. **Predict before measuring.** Before a performance measurement, the
   predicted value is written down from shape, array size and buffer sizes;
   then it is measured and any gap is explained.
7. **Tests are not weakened to make them pass.** A failing test is never
   deleted, skipped or loosened without a recorded reason in
   `docs/DECISIONS.md`.
8. **Reproducible randomness.** Every random test logs its seed and reads
   `SYSARRAY_SEED` when set, so any failure can be replayed exactly.
9. **Lint clean.** `make lint` reports zero Verilator `-Wall` warnings. A
   waiver needs a `/* verilator lint_off ... */` comment with the reason.

## SystemVerilog

- File name = module name, `snake_case`, prefixed `sa_` (e.g. `sa_pe`,
  `sa_array`). One module per file.
- Parameters in `UPPER_CASE`: `S`, `DATA_W = 8`, `ACC_W = 32`.
- Registered signals end in `_q`, next-state values in `_d`. Clock `clk`.
- Handshakes are `*_valid` / `*_ready`: a transfer happens when both are high
  on a rising edge; `valid` never depends combinationally on `ready`, and data
  stays stable while `valid && !ready`.

## cocotb / Python

- cocotb 2.x APIs: `cocotb_tools.runner`, `LogicArray`, `.value.to_signed()`.
- Each testbench lives in `tb/<block>/`: the cocotb module is
  `cocotb_<block>.py` and the pytest launcher is `test_<block>.py`. The
  launcher calls the shared runner in `tb/common/`, so pytest never imports
  cocotb test functions directly.
- Python is typed and formatted with `ruff`.

## Results

- `results/` holds measured data only. Each file is named after the commit
  that produced it and comes from a committed script (index:
  `docs/RESULTS.md`). Simulation output (`sim_build/`, waveforms) is never
  committed.
