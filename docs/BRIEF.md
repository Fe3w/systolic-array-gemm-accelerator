# SysArray — Technical Brief

The technical brief for SysArray, written before the RTL: what to build, how
it is verified and how it is measured. Design choices made along the way live
in `docs/DECISIONS.md`; the built design is described in `docs/ARCHITECTURE.md`
and `docs/spec/`.

Items marked **(proposed)** were starting points, not final decisions; the
outcome of each is recorded in `docs/DECISIONS.md`. Milestone labels (M1, M2,
...) name the order in which the parts were built.

---

## 1. Purpose

Build a small accelerator that can be defended end to end: the dataflow choice,
the RTL, the verification, the compiler mapping and the measured cost.

Four parts, each checkable: RTL design, real verification, a compiler that
targets this hardware, and power/performance/area (PPA) numbers.

**Context.** GEMM optimized in software (CPU cache blocking, GPU shared-memory
tiling, TF32 WMMA on Tensor Cores) is the starting point; SysArray is the
hardware half of the same problem.

## 2. Glossary

| Term | Meaning here |
| --- | --- |
| GEMM | C = A × B with A: M×K, B: K×N, C: M×N |
| S | Side of the square PE array (S = 4 bring-up, S = 8 for results). The project brief calls this N; this document uses S to avoid clashing with the GEMM dimension N |
| PE | Processing element: one int8 × int8 multiply plus int32 add per cycle |
| MAC | Multiply-accumulate, `acc += a * w` |
| Weight-stationary (WS) | Each PE holds one weight for a whole tile; activations move right, partial sums move down |
| Tile | The S×S block of B currently held in the array, plus the activation rows streamed through it |
| Skew / de-skew | Delaying array row r by r cycles on input, and column c by S−1−c cycles on output, so operands meet in the right cycle |
| Fill / drain | Cycles spent filling the empty array and emptying it, about 2S − 1 per tile |
| Utilization | Useful MACs ÷ (S² × total cycles) |
| PPA | Power, performance, area. Here: cycles/utilization, LUT/DSP/Fmax (FPGA), mm² and slack (SKY130) |

## 3. Problem definition and arithmetic

- **Operation:** C[m][n] = Σ_k A[m][k] · B[k][n].
- **A (activations)** and **B (weights)** are signed int8 (two's complement,
  −128 … 127). **C** is signed int32.
- **Product range:** the largest magnitude is (−128)·(−128) = 16384 = 2¹⁴.
- **Overflow bound:** |C| ≤ K · 2¹⁴. This fits in int32 (≤ 2³¹ − 1) for
  K ≤ 131071. Every benchmark shape here has K ≤ 3072, so overflow cannot
  happen on real shapes. Overflow behaviour still has to be defined and
  tested with directed tests that force it.
- **Accumulator semantics (proposed, D-004):** two's-complement wrap at 32
  bits, matching NumPy `int32` arithmetic. Alternative: saturation.
- **Golden model:** `compiler/sysarray/golden.py` computes the expected C with
  int64 intermediates, then applies the chosen int32 semantics. It is
  unit-tested against `numpy.matmul`.

## 4. Architecture overview

```
 Python tiling compiler ──► command stream (LOAD_W, LOAD_A, COMPUTE, STORE)
                                   │
                                   ▼
                          ┌──────────────────┐
                          │  Controller FSM  │  decodes commands, sequences blocks
                          └────────┬─────────┘
                                   │ control
     ┌──────────────┐  valid/ready ▼
     │ Memory model │◄──────────► DMA ─────────────────────────────┐
     │ (cocotb)     │                │                             │ STORE
     └──────────────┘                ▼                             │
                     ┌──────────────────────────┐                  │
                     │ Input buffer (int8)      │──skew──►┌────────┴────────┐
                     │ Weight buffer (int8)     │──load──►│  S×S PE array   │──de-skew──► Accumulator
                     └──────────────────────────┘         │ weight-stationary│            buffer (int32)
                                                          └─────────────────┘
 Around everything: cocotb testbenches drive commands and check results against NumPy.
```

Data path for one tile: LOAD_W puts an S×S weight block into the PEs. LOAD_A
fills the input buffer with a strip of activation rows. COMPUTE streams those
rows through the array and adds the results into the accumulator buffer.
STORE writes finished int32 outputs back to memory.

## 5. Dataflow and timing

### 5.1 Mapping (weight-stationary)

- PE(r, c), with row r and column c in 0..S−1, holds weight
  `W[r][c] = B[k0 + r][n0 + c]` for the current tile.
- Activation `A[m][k0 + r]` enters array row r from the left and moves one
  column right per cycle.
- Partial sums enter at the top (zero, or nothing) and move one row down per
  cycle. Each PE computes `psum_out = psum_in + a_in · w` and registers both
  `a_out` and `psum_out`.
- The bottom of column c produces Σ_r A[m][k0+r] · B[k0+r][n0+c], the
  contribution of this K-slice to C[m][n0 + c]. The accumulator buffer adds
  contributions across K-slices.

### 5.2 Skew and de-skew

With one register per hop, the partial sum for activation row m reaches
PE(r, c) at cycle m + r + c. Activation `A[m][k0+r]` must also arrive there at
cycle m + r + c. Since it travels c hops to the right, it must enter row r at
cycle m + r. So **row r is delayed by r cycles** (input skew).

Column c's result for row m leaves the array at about cycle m + S + c. To line
outputs up by row, **column c is delayed by S − 1 − c cycles** (output
de-skew).

### 5.3 Cycle model (predicted, analytical)

For one tile with M_c activation rows streamed through:

- **Weight load:** L_w cycles (≈ S if weights shift down the columns one row
  per cycle; the M3/M4 design fixes the exact value).
- **Fill:** about S − 1 cycles before the first full diagonal.
- **Steady state:** one activation row enters per cycle, so S² MACs per cycle.
- **Drain:** about S − 1 cycles after the last row enters, plus de-skew.
- **Total per tile:** T_tile ≈ L_w + M_c + 2S − 1 (exact constants are
  measured in M4 and replace these in `docs/spec/array.md`).
- **Measured (M4):** with the shift-chain weight load (D-012), L_w = S
  exactly, and from the first `w_load` to the cycle after the last output
  T_tile = M_c + 3S − 1; latency from an activation row to its output row is
  2S − 1. Every measured row of `results/latency/latency_44b58e7.csv`
  (S = 4, 8; M_c = 1, 2, 8, 13, 64) equals these formulas, e.g. S = 8,
  M_c = 64 → T_tile = 87 cycles.
- **After M7b (two-stage MAC, D-022):** latency 2S and T_tile = M_c + 3S;
  every row of `results/latency/latency_d4aedec.csv` matches (S = 8,
  M_c = 64 → T_tile = 88 cycles).
- **Tile utilization:** U_tile ≈ M_c / (L_w + M_c + 2S − 1) when nothing
  overlaps. For S = 8 this rises with M_c. Small M_c is dominated by
  fill/drain and weight load.

Without double buffering (MVP), DMA transfers do not overlap compute, so
T_total = T_dma + T_compute. This is a known MVP limitation and a reason
utilization will be below the array-only number.

### 5.4 Roofline

- **Peak compute:** S² MACs per cycle (64 for S = 8).
- **Off-array bytes per tile:** S² weight bytes + M_c · S activation bytes
  (+ output stores, amortized over K).
- **Arithmetic intensity** (MACs per byte moved by DMA):
  I = (M_c · S²) / (S² + M_c · S) = M_c · S / (S + M_c), which approaches S for
  large M_c.
- **Attainable:** min(S², I · BW_dma), where BW_dma is DMA bytes per cycle.
  For S = 8 and large M_c, the array needs about 8 bytes per cycle of DMA
  bandwidth to stay compute-bound once transfers overlap compute.
- The measurement milestone plots measured MACs/cycle against this roofline
  for every benchmark shape.

## 6. Block specifications

Each block gets a spec in `docs/spec/<block>.md` **before** its RTL. The spec
has ports, a cycle table, reset behaviour, and the test plan.

### 6.1 Processing element `sa_pe` (proposed interface)

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk` | in | 1 | clock |
| `rst` | in | 1 | reset (style per D-005) |
| `w_load` | in | 1 | capture `w_in` into the weight register this cycle |
| `w_in` | in | 8 signed | weight being loaded (shifted down the column during LOAD_W) |
| `w_out` | out | 8 signed | registered weight passed to the PE below during load |
| `a_in` | in | 8 signed | activation from the left |
| `a_valid_in` | in | 1 | activation is valid |
| `a_out` / `a_valid_out` | out | 8 signed / 1 | registered activation and valid to the right |
| `psum_in` | in | 32 signed | partial sum from above |
| `psum_out` | out | 32 signed | registered `psum_in + a_in * w_q` |

Notes:
- The multiply is 8×8 signed into a 16-bit product, sign-extended to 32 bits
  before the add.
- If timing (M7) shows the multiply-add is the critical path, add a pipeline
  stage. That changes the skew and the cycle model, so update the specs and
  tests.
- PE tests: exhaustive 256 × 256 products, accumulation chains, weight hold
  while activations change, weight load shifting, reset values, valid
  propagation, and the −128 × −128 corner.

### 6.2 Array `sa_array`

- Parameter `S`. Built with `generate` loops from `sa_pe`.
- Weight load: weights shift down each column over S cycles (proposed), or are
  written row-parallel from the weight buffer (alternative). Record the choice.
- Input skew registers on the west edge and output de-skew registers on the
  south edge, inside or beside the array (record the choice).
- Exposes: `S` activation inputs plus valids, `S` int32 outputs plus valids.
- Tests: directed 4×4 cases (identity, single non-zero, all −128), random
  S×S×M tiles vs golden, latency measured in cycles vs §5.3, back-to-back
  tiles with no idle cycles.

### 6.3 Buffers (proposed sizes, confirmed in M5)

| Buffer | Content | Proposed size (S = 8) | Banking |
| --- | --- | --- | --- |
| Input | int8 activations, rows of S bytes | 256 rows × 8 B = 2 KiB | S banks or one S-byte-wide port, so one full row per cycle |
| Weight | int8 S×S tile | 64 B (one tile) | Row-wide port, S bytes per cycle |
| Accumulator | int32 partial/final sums, rows of S words | 256 rows × 8 × 4 B = 8 KiB | S-word-wide; read-modify-write every cycle in steady state |

- The accumulator does read-add-write every cycle, so the read and write ports
  cannot conflict. Use a 1-read/1-write port memory model and handle the
  read-to-write latency (forwarding or a schedule that never reads a row being
  written).
- Buffer models are behavioural SystemVerilog arrays that Yosys can infer as
  RAM or registers. LibreLane runs (§9.5) may exclude buffers.
- Buffer depth sets the largest activation strip M_c per pass, which sets
  utilization (§5.3) and tile order (§7).

### 6.4 Memory model and DMA

- **Memory model:** a byte-addressable memory in cocotb (Python) behind a simple
  valid/ready request/response interface. Latency and bandwidth are
  configurable, so utilization can be studied against BW_dma.
- **DMA:** moves rectangular blocks between memory and a buffer: base address,
  row stride, number of rows, bytes per row, buffer offset. One request
  interface plus one data interface, both valid/ready.
- **Handshake rules:** a transfer happens when `valid && ready` on a rising
  edge. `valid` never depends combinationally on `ready`. Data stays stable
  while `valid && !ready`. Tests apply random backpressure.

### 6.5 Command interface (proposed encoding, finalized in M8)

| Field | Meaning |
| --- | --- |
| `op` | LOAD_W, LOAD_A, COMPUTE, STORE |
| `mem_addr`, `mem_stride` | memory side of the transfer (LOAD_*/STORE) |
| `buf_addr` | buffer row offset |
| `rows` | number of rows (activation rows, or output rows) |
| `acc_mode` | COMPUTE only: `OVERWRITE` (first K-slice) or `ACCUMULATE` |

- Commands arrive over a valid/ready command port. The controller accepts the
  next command only when it can run it safely (simple in-order execution in
  the MVP).
- **Errors** (at minimum): unknown opcode, `rows` beyond buffer depth, COMPUTE
  before any LOAD_W. Report through a sticky error flag plus an error code. Do
  not hang.

### 6.6 Controller `sa_ctrl`

- **States (proposed):** IDLE → DECODE → {LOAD_W, LOAD_A, COMPUTE, STORE} →
  DONE → IDLE, plus ERROR.
- Sequences DMA requests, buffer reads/writes and array enables, and counts
  cycles in each state for performance counters (`cycles_total`,
  `cycles_compute`, `cycles_dma`, `macs_issued`). The counters feed the
  measurement milestone.
- Tests: each command alone, all command pairs back to back, error cases,
  random command streams from the compiler.

## 7. Tiling compiler (Python package `sysarray`)

**Input:** M, N, K, array size S, buffer depths, tile order.
**Output:** a command stream (list and binary/hex file the testbench replays),
plus a predicted cycle count and traffic report.

### 7.1 Tiling

- Split K and N into S-sized slices; split M into chunks of M_c ≤ input/
  accumulator buffer depth.
- **Remainders:** pad partial tiles with zeros (padded MACs count as wasted,
  not useful). Test with shapes that are not multiples of S.

### 7.2 Two tile orders to compare

- **Order A — weight-reuse first:** `for n_t: for k_t: LOAD_W; for m_c:
  LOAD_A; COMPUTE(acc_mode = OVERWRITE if k_t == 0 else ACCUMULATE)`, then
  STORE every m_c of this n_t. Each weight tile is loaded once. It needs the
  accumulator to hold all M rows of an S-wide column strip, otherwise it must
  fall back to chunking M.
- **Order B — output-tile first:** `for m_c: for n_t: for k_t: LOAD_W; LOAD_A;
  COMPUTE`, then STORE. It needs only M_c rows of accumulator, but reloads every
  weight tile ⌈M / M_c⌉ times.
- The compiler reports, for each order: weight bytes loaded, activation bytes
  loaded, output bytes stored, commands issued, and predicted cycles. The
  measurement milestone compares those predictions with measured cycles.

### 7.3 Predictor

`sysarray.predict(M, N, K, S, buffers, order, bw_dma)` returns predicted cycles,
utilization and DMA bytes using §5.3–§5.4. It is labelled "predicted
(analytical)" everywhere it appears.

## 8. Verification plan

| Level | What | Pass criterion |
| --- | --- | --- |
| Golden model | `golden.py` vs `numpy.matmul` (int64), plus wrap semantics | pytest green |
| PE | exhaustive 65,536 int8 products; accumulation; weight load/hold; reset; valid propagation | all pass |
| Array | directed 4×4; random S×S×M vs golden; fill/drain latency vs §5.3 | all pass; latency table in `docs/spec/array.md` |
| Buffers + DMA | random block transfers with random backpressure; port conflicts | data identical, no drops |
| Accumulator | OVERWRITE vs ACCUMULATE; read-modify-write hazards | matches golden |
| Controller | every command; every back-to-back pair; error cases | correct results, error flags, no hangs |
| System | compiler-generated command streams for random shapes (including non-multiples of S) | **≥ 1,000 random GEMMs, 0 failures** |
| Corners | all −128, all 127, mixed signs, K forcing int32 wrap, M = 1, N = 1, K = 1 | match golden |

- Every random test prints its seed and honours `SYSARRAY_SEED`.
- CI runs the full fast suite on every push. A long run (the ≥ 1,000 GEMM
  campaign) can sit behind an environment variable (`SYSARRAY_LONG=1`). Its
  result summary is committed to `results/verification/`.
- Waveforms (FST/VCD) are generated on demand, not committed. The README uses
  screenshots of one full tile: load, compute, drain.

## 9. Measurement plan

### 9.1 Definitions

- `useful_macs = M · N · K` (padded MACs excluded).
- `utilization = useful_macs / (S² · cycles_total)`.
- `cycles_total` is counted by the hardware performance counters, from the
  first command accepted to the last STORE completed.

### 9.2 Benchmark shapes

| ID | M | N | K | Why |
| --- | --- | --- | --- | --- |
| sq8 | 8 | 8 | 8 | fits in one tile |
| sq16 | 16 | 16 | 16 | tiles evenly |
| sq64 | 64 | 64 | 64 | many tiles |
| sq256 | 256 | 256 | 256 | buffer pressure |
| bert_proj | 128 | 768 | 768 | BERT-base attention projection (seq 128, hidden 768) |
| bert_ffn_down | 128 | 768 | 3072 | BERT-base FFN down-projection (the brief's 128×768×3072) |
| bert_ffn_up | 128 | 3072 | 768 | BERT-base FFN up-projection (optional) |
| r50_3x3 | 3136 | 64 | 576 | ResNet-50 conv2_x 3×3, 64→64 on 56×56, as im2col GEMM |
| r50_1x1 | 3136 | 256 | 64 | ResNet-50 conv2_x 1×1, 64→256 on 56×56, as im2col GEMM |
| odd | 100 | 37 | 53 | remainders and underutilization |

At least 6 shapes must be measured, including BERT and ResNet ones. Large
shapes may be simulated with Verilator at reduced repeat counts. Record exactly
what was simulated.

### 9.3 Output files

- `results/perf/<run_id>.csv` with columns: `shape_id, M, N, K, S, order,
  bw_dma, cycles_total, cycles_compute, cycles_dma, useful_macs, utilization,
  predicted_cycles, predicted_utilization, git_commit, seed`.
- `results/perf/<run_id>_utilization.png`: utilization per shape and order,
  measured vs predicted.
- `results/scalesim/`: SCALE-Sim config, topology CSV and outputs for the same
  S = 8 weight-stationary configuration and shapes, plus a short comparison
  note.

### 9.4 FPGA synthesis (Yosys + nextpnr)

- Target family **(proposed, D-006): Lattice ECP5** with `nextpnr-ecp5`. It
  has enough 18×18 multipliers for 64 MACs. iCE40 UP5K has too few DSP blocks.
- Flow script in `scripts/synth/` (for example `synth_ecp5` then
  `nextpnr-ecp5 --85k ... --report`). Record LUTs, FFs, DSPs (MULT18X18D),
  BRAM, and Fmax.
- Output: `results/synth/<target>_<git_commit>.json` plus the raw reports.
- Find the critical path from the timing report. If it is the multiply-add,
  pipeline it and show before and after.

### 9.5 ASIC flow (LibreLane on SKY130) — Extension

- Run `sa_array` (S = 8), or a single PE row or S = 4 if the full array is too
  slow to route. Buffers are excluded unless SRAM macros are added (out of
  MVP).
- Record: die/core area (mm²), cell count, worst setup slack and hold slack
  at the target clock, and the clock period used.
- Output: `results/asic/<config>_<git_commit>/` with the config and the
  summary metrics. State exactly what was run.

### 9.6 Honesty rules

- Numbers come only from `results/`. Predictions are labelled.
- Poor utilization is explained with §5.3–§5.4 and SCALE-Sim, not hidden.

## 10. Success criteria

| Criterion | Target | Type |
| --- | --- | --- |
| Random GEMM tests vs NumPy | ≥ 1,000 passing, 0 failures | MVP |
| Array size with results | 8×8 int8 | MVP |
| GEMM shapes measured | ≥ 6, including BERT and ResNet layer shapes | MVP |
| FPGA synthesis report | LUTs, DSPs, Fmax recorded | MVP |
| Tiling orders compared | ≥ 2, with utilization per shape | MVP |
| ASIC run (LibreLane, SKY130) | area and worst slack recorded | Extension |

## 11. Scope

| Part | MVP | Extension | Out of scope |
| --- | --- | --- | --- |
| PE + S×S weight-stationary array | Yes | Output-stationary variant for comparison | |
| Input/weight/accumulator buffers, DMA | Yes | Double buffering | Caches |
| Command interface + controller FSM | Yes | | Full ISA |
| cocotb tests vs NumPy | Yes | Coverage, formal checks on the PE | UVM |
| Python tiling compiler | Yes | MLIR `linalg.matmul` front end | General DNN compiler |
| Yosys/nextpnr synthesis | Yes | Quartus on a lab board | |
| LibreLane on SKY130 | | Yes | Tape-out |
| bf16 datapath | | Yes | |
| Host CPU integration | | Via a later custom-instruction project | Linux SoC |

## 12. Deliverables

- This repository with `rtl/`, `tb/`, `compiler/`, `scripts/`, `results/`, and
  CI running the test suite on Verilator.
- README: block diagram, dataflow explanation, utilization plot per GEMM shape,
  resource and timing table, one-command reproduction.
- Waveform screenshots of one full tile (load, compute, drain).
- A short write-up comparing measured utilization with SCALE-Sim for the same
  configuration.
- Tag `v0.1` at the MVP gate, `v0.2` after the ASIC run or an extension.

## 13. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Off-by-one timing in skew/de-skew | Bring up at S = 4 with waveforms; directed tests before random ones; cycle tables in specs |
| Scope creep (bf16, SoC, Linux) | Extensions only after the MVP gate |
| Low Fmax | Pipeline the MAC early; report Fmax honestly |
| Accumulator read-modify-write hazards | Spec the port timing first; directed back-to-back tests |
| Simulation too slow for big shapes | Verilator; reduced repeats; record exactly what ran |
| LibreLane slow or failing on the full array | Run a PE row or S = 4; report what was run |
| Toolchain drift in cloud sessions | `make check` enforces versions; OSS CAD Suite pinned via `OSS_CAD_VERSION` if needed |
| Utilization looks poor | Explain it with the roofline and SCALE-Sim; that analysis is the point |

## 14. Concepts this design exercises

- Why systolic arrays reduce memory traffic (operand reuse across a grid).
- Weight-, output- and input-stationary trade-offs: what stays, what moves,
  what limits each.
- How skewing aligns operands; fill and drain cost of about 2S − 1 cycles.
- How buffer size and tile shape set reuse and utilization.
- The array's roofline: peak MACs/cycle vs DMA/buffer bytes/cycle.
- How SysArray compares with NVIDIA Tensor Cores (register-fed fused MMA
  units inside SMs) and the TPU's matrix unit (a 256×256 weight-stationary
  systolic array fed from large on-chip SRAM).

## 15. References

- H. T. Kung, "Why Systolic Architectures?", IEEE Computer, 1982.
- N. Jouppi et al., "In-Datacenter Performance Analysis of a Tensor Processing
  Unit", ISCA 2017. https://arxiv.org/abs/1704.04760
- V. Sze, Y.-H. Chen, T.-J. Yang, J. Emer, "Efficient Processing of Deep
  Neural Networks: A Tutorial and Survey", Proc. IEEE 2017.
- Y.-H. Chen, J. Emer, V. Sze, "Eyeriss", ISCA 2016 / JSSC 2017.
- H. Genc et al., "Gemmini: Enabling Systematic Deep-Learning Architecture
  Evaluation via Full-Stack Integration", DAC 2021.
  https://github.com/ucb-bar/gemmini
- A. Parashar et al., "Timeloop", ISPASS 2019.
- R. Raj et al., "SCALE-Sim v3", ISPASS 2025. https://arxiv.org/abs/2504.15377
- cocotb 2.x documentation: https://docs.cocotb.org
- OSS CAD Suite: https://github.com/YosysHQ/oss-cad-suite-build
- LibreLane: https://github.com/librelane/librelane
