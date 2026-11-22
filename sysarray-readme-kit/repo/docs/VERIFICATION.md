# Verification

How SysArray is checked, from one PE up to whole GEMMs driven by the compiler.
Every number comes from a file in `results/` (cited next to it). Back to the
[README](../README.md).

## Method

- **Spec first, then test, then RTL.** Every block has a spec with a
  cycle-by-cycle table (`docs/spec/`) and a cocotb testbench written before
  its RTL, shown failing first and then passing (rules 2 and 5 in
  [CONVENTIONS.md](CONVENTIONS.md)).
- **NumPy is the golden model.** `compiler/sysarray/golden.py` computes
  int8 × int8 → int32 with the hardware's overflow semantics (int32 wrap, D-004)
  and is itself unit-tested against plain NumPy.
- **Block level → system level.** One cocotb testbench per block, run on
  Verilator through pytest: PE, register, SRAM, PE grid, array (with skew and
  de-skew), feeder, accumulator, DMA, core, top, plus end-to-end GEMM,
  performance and latency benches (`tb/`).
- **Command-level model.** `sa_top` is checked against a functional model of
  the command semantics (`compiler/sysarray/funcsim.py`) with random programs
  that cover all 16 ordered pairs of LOAD_W, LOAD_A, COMPUTE and STORE,
  including back-to-back commands.
- **Exact timing, not just correct values.** Where the memory never stalls,
  the RTL's cycle counters are checked against the performance model's
  prediction, cycle for cycle.
- **Reproducible randomness.** Every random test logs its seed and replays
  with `SYSARRAY_SEED=<n>`; CI runs a fast subset twice with the same seed
  and checks both runs agree (`make test-repro`).
- **Lint clean.** `make lint` runs Verilator `-Wall` on every RTL file with
  zero warnings; CI runs lint and all tests on every push.

## Random campaign

`make campaign` runs random GEMMs through the whole stack: the compiler tiles
them, the RTL runs the command stream against a memory model with random
latency and backpressure, and C is compared with NumPy.

Latest run (`results/verification/campaign_cd2849e.json`, S = 8):

| What | Value |
| --- | --- |
| Random compiler-driven GEMMs | 1,000, 0 failures |
| Shapes not a multiple of S | 972 of 1,000 (exercises padding and partial tiles) |
| Shape range | M, N, K up to 35 each |
| Tile orders | A: 494, B: 506 |
| Memory read latency | 1–4 cycles, each about a quarter of runs |
| Memory stall probability | 0, 0.1 or 0.3 per cycle |
| Exact-timing checks (measured = predicted cycles) | 271 |
| Corner cases | all −128, all 127, mixed signs, M = N = K = 1, M = 1, N = 1, K = 1, int32 wrap at K = 131,072: all pass |
| Wall clock | 132.7 s |

Two earlier campaigns (`results/verification/campaign_126930e.json`,
`results/verification/campaign_3dbf80b.json`) also ran 1,000 GEMMs each with
0 failures. The campaign's random shapes are small (up to 35) to keep it fast;
the large BERT and ResNet-50 shapes are checked against NumPy in every
`make perf` run (16 / 16 correct, `results/perf/be6f466.csv`).

## What is not covered

- No formal verification (out of scope for this project).
- The ECP5 DSP simulation model used for the `SA_ECP5_DSP` build is our own:
  Yosys ships no simulation model for `MULT18X18D`, so it is not checked
  against Lattice's (D-027).
- Exact-timing checks apply only to non-stalling memory runs (D-025).

## Reproduce

```bash
make check lint test    # versions, lint, all Python + RTL tests (~6 min on 4 cores)
make campaign           # 1,000 random GEMMs (~2 min) -> results/verification/
SYSARRAY_SEED=<n> make test-rtl   # replay a failing random test
```

To watch any test's waveforms, see [waveforms/README.md](waveforms/README.md).
