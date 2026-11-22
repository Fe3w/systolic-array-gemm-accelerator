# Design Decisions

One entry per decision. Status: `DECIDED` (final), `PROPOSED` (chosen and
built, the option easiest to reverse; open to revision), or `superseded`.
Never delete an entry; supersede it with a new one and link back.

Template:

```
## D-<nnn> <title>
Date: YYYY-MM-DD · Status: DECIDED | PROPOSED · Milestone: M<k>
Context: why this needs deciding.
Decision: what was chosen.
Alternatives: what else was considered, and why not.
Consequences: what this changes (files, timing, tests).
```

---

## D-001 Dataflow: weight-stationary
Date: 2026-11-12 · Status: DECIDED · Milestone: —
Context: The brief targets a weight-stationary array like the TPU v1 matrix unit.
Decision: Weight-stationary. Each PE holds one weight per tile; activations move right, partial sums move down.
Alternatives: Output-stationary (keeps partial sums local and avoids accumulator read-modify-write, but moves weights every cycle); input-stationary. An output-stationary variant is an extension.
Consequences: Weight reuse = M rows per tile; needs skew/de-skew and an accumulator buffer for K > S.

## D-002 Arithmetic: int8 inputs, int32 accumulation
Date: 2026-11-12 · Status: DECIDED · Milestone: —
Context: Inference-style quantized GEMM.
Decision: Signed int8 activations and weights; signed int32 partial sums and outputs.
Alternatives: uint8 activations (asymmetric quantization); bf16 (extension).
Consequences: Product fits in 16 bits; overflow impossible for K ≤ 131071 (BRIEF §3).

## D-003 Array size
Date: 2026-11-12 · Status: DECIDED · Milestone: —
Decision: Parameter S. S = 4 for bring-up, S = 8 for all reported results.

## D-004 Accumulator overflow semantics
Date: 2026-11-12 · Status: DECIDED (see D-004a) · Milestone: M1
Context: Overflow cannot happen on benchmark shapes but must be defined and tested.
Decision (proposed): Two's-complement wrap at 32 bits, matching NumPy int32.
Alternatives: Saturation. More robust numerically, costs a comparator per accumulator, and differs from NumPy's default.
Consequences: Golden model `semantics="wrap"`; directed overflow tests in M1/M2.

## D-005 Reset style
Date: 2026-11-12 · Status: PROPOSED · Milestone: M1
Decision (proposed): Synchronous, active-high `rst`. Reset control state and valid bits; leave pure datapath registers (activation, psum pipelines) unreset where valid bits gate them.
Alternatives: Asynchronous active-low `rst_n` (common in ASIC flows); resetting every flop (simpler to reason about, more area and fan-out).
Consequences: Tests must check that no invalid data is ever marked valid after reset.

## D-006 FPGA synthesis target
Date: 2026-11-12 · Status: PROPOSED · Milestone: M7
Decision (proposed): Lattice ECP5 with `nextpnr-ecp5`. It has enough 18×18 multiplier blocks for 64 MACs.
Alternatives: iCE40 UP5K (too few DSP blocks for 64 MACs); Gowin (less mature open flow); a vendor tool on a lab board (extension).
Consequences: `scripts/synth/` targets ECP5; DSP count reported as MULT18X18D.

## D-007 Test file layout
Date: 2026-11-12 · Status: DECIDED · Milestone: —
Decision: `tb/<block>/cocotb_<block>.py` holds cocotb tests; `tb/<block>/test_<block>.py` is the pytest launcher that calls `tb/common/runner.py`.
Alternatives: cocotb Makefiles per testbench. Rejected: pytest gives one entry point for CI and seeds.

## D-008 Toolchain versions
Date: 2026-11-12 · Status: DECIDED · Milestone: —
Decision: cocotb 2.x (`cocotb>=2.0,<3`) with Verilator ≥ 5.036 from OSS CAD Suite. Ubuntu's apt Verilator is too old for cocotb 2.x.
Consequences: `make check` enforces the versions; cloud sessions install OSS CAD Suite.

## D-004a Accumulator overflow semantics — M1 review
Date: 2026-11-12 · Status: DECIDED · Milestone: M1
Context: D-004 asked for confirmation in M1. The golden model now implements both options and tests them (`compiler/tests/test_golden.py::test_overflow_wraps_like_int32`, `::test_saturate_semantics_clamps`).
Decision: Two's-complement wrap at 32 bits (the default of `golden.gemm`). Binding for the M2 PE adder.
Alternatives: Saturation, available as `semantics="saturate"` for comparison.
Consequences: Had saturation been chosen, M2's PE tests would switch `semantics` and the PE adder would gain overflow detection and a clamp.

## D-005a Reset style applied in M1
Date: 2026-11-12 · Status: PROPOSED · Milestone: M1
Context: First RTL (`rtl/common/sa_reg.sv`) and the PE spec needed D-005 in concrete form.
Decision: Keep D-005. Valid bits reset; data registers do not. In the PE (`docs/spec/pe.md` §5) the weight register `w_q` is also not reset; COMPUTE before LOAD_W is a controller error (M8).
Alternatives: Reset `w_q` to 0, which makes an early COMPUTE give 0 instead of garbage (+8 reset flops per PE, 512 for S = 8).
Consequences: `tb/reg` tests check that valid data presented during reset never appears afterwards, and that a mid-stream reset flushes all valid bits.

## D-009 Python import layout
Date: 2026-11-12 · Status: PROPOSED · Milestone: M1
Context: Tests need `sysarray` and the shared testbench helpers importable, both in pytest and inside the simulator process.
Decision: No package install. `pytest.ini` sets `pythonpath = compiler .`, so `import sysarray` and `import tb.common.*` work. The cocotb runner forwards `sys.path` to the simulator as PYTHONPATH, so cocotb modules are named fully (`tb.reg.cocotb_reg`). Tool config (ruff, black, line length 100) lives in `pyproject.toml`.
Alternatives: `pip install -e compiler/` (one more setup step in every environment, including CI and the cloud hook).
Consequences: Running tests requires starting pytest from the repo root (the Makefile does).

## D-010 Seed handling in testbenches
Date: 2026-11-12 · Status: PROPOSED · Milestone: M1
Context: `docs/CONVENTIONS.md` rule 8: every random test logs its seed and honours SYSARRAY_SEED.
Decision: `tb/common/runner.py` picks the seed (SYSARRAY_SEED if set, else a fresh 31-bit value), prints it with a replay command, and passes it to the simulator as both cocotb's `COCOTB_RANDOM_SEED` and `SYSARRAY_SEED`. Tests use `utils.get_rng(<test name>)`, a private `random.Random` seeded with `"<seed>:<test name>"`, so adding a test never changes another test's stimulus. `make test-repro` (`scripts/check_repro.sh`) runs the RTL suite twice with seed 1 and diffs the seed-dependent log lines; CI runs it.
Alternatives: One global RNG (reordering tests changes stimulus); NumPy generators (not needed for bit-level stimulus).
Consequences: Golden-model tests use a fixed default seed (20261112) unless SYSARRAY_SEED is set.

## D-011 PE: invalid activations contribute zero
Date: 2026-11-12 · Status: DECIDED · Milestone: M2
Context: Whether `psum_out` should depend on `a_valid_in`.
Decision: `psum_out = psum_in + (a_valid_in ? a·w : 0)` (`docs/spec/pe.md` §1). Bubbles in the activation stream then pass partial sums through unchanged.
Alternatives: Ungated MAC (slightly smaller; relies on the controller never letting garbage through).
Consequences: One extra M2 test (invalid activation passes psum through). An AND/mux in front of the adder, which may show up in M7 timing.

## D-012 Weight load through a per-column shift chain
Date: 2026-11-12 · Status: DECIDED for M2; M3 may revisit with a new entry · Milestone: M2/M3
Context: BRIEF §6.2 lists shift-down vs row-parallel weight loading.
Decision: For M2, `w_q` doubles as the shift-chain stage (`w_out = w_q`), with `w_load` broadcast. L_w = S cycles (predicted, analytical). No compute while loading.
Alternatives: Row-parallel write from the weight buffer (1 cycle per row but S write enables and an S-row address decoder); a separate shadow register for double buffering (an extension).
Consequences: M3 confirms or replaces this when the array and weight buffer are designed.

## D-013 Toolchain in cloud environments
Date: 2026-11-12 · Status: superseded by D-013a · Milestone: M1
Context: In the sandboxed cloud development environment, `scripts/install_eda.sh` gets HTTP 403 from api.github.com (GitHub access is limited to this repository), so the OSS CAD Suite release (a GitHub release of YosysHQ/oss-cad-suite-build) cannot be downloaded. `make check` fails there. CI (GitHub Actions, `YosysHQ/setup-oss-cad-suite@v4`) is unaffected.
Decision: Open at the time. Options:
  (a) Add `scripts/cloud_setup_script.sh` as the cloud environment's setup script and make sure the environment can download GitHub release assets (setup scripts may run under different network rules; to be confirmed).
  (b) Give the environment read access to `YosysHQ/oss-cad-suite-build` so the existing setup works.
  (c) Accept CI as the only simulator for cloud work: write tests and RTL, push, and read CI results. Slower iteration (one CI run ≈ minutes per attempt) and no local waveforms.
Consequences: Until resolved, every cloud change to RTL depends on CI to run simulations.

## D-013a Toolchain in cloud environments: conda-forge
Date: 2026-11-12 · Status: PROPOSED · Milestone: M1
Context: D-013. Options tried in order, stopping at the first that works: (a) conda-forge, (b) Docker Hub image, (c) source build, (d) CI only.
Decision: Rung (a). `scripts/install_eda.sh` downloads micromamba from micro.mamba.pm and creates `/opt/eda` from conda-forge with `verilator>=5.036` and `yosys` (conda-forge build of Verilator 5.054 and Yosys 0.69+ at the time of writing). nextpnr-ecp5 comes from PyPI as `yowasp-nextpnr-ecp5` (nextpnr 0.11.1, WebAssembly), because conda-forge has no nextpnr-ecp5 and litex-hub's is older (0.5). A fresh install took about 13 s in the cloud environment. `session_start.sh` puts `/opt/eda/bin` on PATH; `cloud_setup_script.sh` does the same for a cached environment. The OSS CAD Suite path remains as `EDA_METHOD=oss-cad-suite` for local machines; CI keeps `YosysHQ/setup-oss-cad-suite`.
Alternatives: (b) Docker Hub image; (c) source build (minutes of compile per fresh VM); (d) CI only (slow iteration, no local waves). Not needed once (a) worked.
Consequences: Cloud and CI use different Verilator builds (conda-forge 5.054 vs OSS CAD Suite devel); both must pass. The yowasp nextpnr is slower than native; M7 measures Fmax with it in cloud runs and should note which build produced each `results/synth/` file.

## D-014 Array structure: PE grid plus skew wrapper
Date: 2026-11-12 · Status: PROPOSED · Milestone: M3
Context: BRIEF §6.2 leaves open whether skew/de-skew registers sit inside or beside the array.
Decision: Two modules. `rtl/array/sa_grid.sv` is the S×S PE grid only (no skew): per-row activations and valids on the west edge, `w_in[c]` on the north edge, `psum_in = 0` on top, per-column `psum_out`/`valid_out` on the south edge (`valid_out[c]` = bottom PE's `a_valid_out`). `rtl/array/sa_array.sv` wraps it with input skew (`sa_reg`, D = r on row r) and output de-skew (`sa_reg`, D = S − 1 − c on column c) and exposes one `a_valid` with an S-element row, `w_load` with an S-element weight row, and S int32 outputs with one `c_valid`. Vector ports are packed `[S-1:0][W-1:0]` (element 0 in the low bits).
Alternatives: One module with skew inside (fewer files, harder to test the grid alone); unpacked array ports (cleaner indexing in SV, but cocotb/Verilator access to unpacked ports is less portable).
Consequences: M3 tests the grid with hand-skewed stimulus first, then the wrapper. Easy to reverse: renaming or merging two files.

## D-015 Weight reload only after the array has drained
Date: 2026-11-12 · Status: PROPOSED · Milestone: M3
Context: With the `w_q` shift chain (D-012), `w_load` overwrites the weights of every PE at once, including PEs still computing earlier activation rows.
Decision: The first `w_load` of the next tile may be asserted no earlier than the cycle of PE(S−1, S−1)'s last MAC for the previous tile, cycle `t_last + 2S − 2` (`t_last` = cycle of the last valid `a_row`). `w_q` changes only at the end of a `w_load` cycle, so that MAC still uses the old weight (refined in M3 from "the cycle after"; `docs/spec/array.md` §3 rule 3). A test exercises the earliest legal cycle, another shows one cycle earlier corrupts; the controller (M8) enforces it.
Alternatives: Shadow weight registers (double buffering, an Extension, out of MVP); a per-row load enable that follows the skew (more control logic, little gain without double buffering).
Consequences: Per-tile overhead of about S (load) + 2S − 1 (drain) cycles, which shows up in utilization (M11) and motivates the double-buffering extension.

## D-016 Buffer sizes (MVP)
Date: 2026-11-12 · Status: PROPOSED · Milestone: M5
Context: BRIEF §6.3 proposes sizes, to be confirmed in M5. The option easiest to reverse was chosen.
Decision: The BRIEF's proposal, as module parameters: input buffer 256 rows × S bytes (2 KiB at S = 8); weight buffer S rows × S bytes (one tile, 64 B); accumulator (M6) 256 rows × S int32 (8 KiB). Depth is a parameter (`DEPTH`), so changing it is a one-line edit plus a test parameter.
Alternatives: Deeper input/accumulator buffers (larger M_c per pass → higher utilization per §5.3, more RAM); two weight tiles (double buffering — an Extension).
Consequences: M_c ≤ 256 per pass; the compiler (M9) chunks M by 256.

## D-017 Behavioural SRAM: 1R1W, 1-cycle read, read-first
Date: 2026-11-12 · Status: PROPOSED · Milestone: M5
Context: Buffers need a simple, synthesizable memory model with defined port-conflict behaviour (BRIEF §6.3).
Decision: `sa_sram`: one write port, one read port, both synchronous; read data appears in the cycle after the read request (1-cycle latency, registered output); a read and a write to the same address in the same cycle returns the **old** data (read-first). No reset of the array contents.
Alternatives: Write-first (new data forwarded; needs a bypass mux); asynchronous read (maps to LUT RAM only, not block RAM).
Consequences: Feeder timing includes one read-latency cycle; the accumulator (M6) must forward or schedule around read-after-write on the same row. M7 checks that Yosys infers block RAM for ECP5 with these semantics.

## D-018 Results name the commit that produced them, on the milestone branch
Date: 2026-11-12 · Status: PROPOSED · Milestone: M5
Context: Milestone PRs are squash-merged, so a commit SHA recorded in a `results/` file (e.g. `latency_44b58e7.csv`) is not an ancestor of `main`.
Decision: Keep recording the SHA of the commit that produced the file. Milestone branches are never deleted, so the SHA stays reachable in the development repository; `docs/RESULTS.md` lists the producing commit and script of every file. (The published copy of the repository starts a fresh history, so these commits are not in it; see D-034.) The squash commit on `main` contains the same tree.
Alternatives: Merge commits instead of squash (keeps SHAs on main, noisier history; squash keeps `main` readable); re-running measurements after merge (doubles CI cost, same numbers).
Consequences: To reproduce a result: `git checkout <sha>` (or the squash commit on main) and run the script named in the file's header/cycle log.

## D-019 Split M6 into M6 (memory model + DMA) and M6b (accumulator + end-to-end)
Date: 2026-11-12 · Status: PROPOSED · Milestone: M6
Context: The M6 draft held three RTL blocks and a model; the plan said to split it if it grew past one cycle.
Decision: M6 = Python memory model + `sa_dma` (LOAD into the buffers, STORE from a generic row source) with random backpressure. M6b = `sa_acc` (OVERWRITE/ACCUMULATE) + `sa_core` integration + the BRIEF's exit (one tile memory → buffers → array → accumulator → memory). Memory bus width = one input row (S × 8 bits; 64 bits at S = 8); an int32 output row is ACC_W / DATA_W = 4 beats.
Alternatives: One large milestone (higher risk of a BLOCKED cycle); a fixed 64-bit bus for every S (S = 4 rows would be half beats).
Consequences: The milestone list gains M6b; later milestone numbers are unchanged.

## D-020 FPGA part and where synthesis runs
Date: 2026-11-12 · Status: PROPOSED · Milestone: M7
Context: D-006 picked ECP5 but not the part; synthesis + place-and-route is slow and the cloud uses yowasp nextpnr (WebAssembly).
Decision: LFE5U-85F, package CABGA381, speed grade 6 (`nextpnr-ecp5 --85k --package CABGA381 --speed 6`): the largest common ECP5, 156 MULT18X18D, enough for 64 MACs. Synthesis is not part of CI; `make synth` runs locally or in a cloud session, and the committed `results/synth/*.json` record tool versions, nextpnr seed and git commit. CI keeps lint + tests.
Alternatives: LFE5U-45F (72 multipliers: enough for 64 MACs, less headroom); synthesis in CI (minutes per push, and a second nextpnr build to keep in sync).
Consequences: Fmax numbers are for this part/speed grade only; any other part needs a new results file.

## D-021 Command interface encoding (MVP)
Date: 2026-11-12 · Status: PROPOSED · Milestone: M8
Context: BRIEF §6.5 lists the command fields and says the encoding is finalized in M8; command encoding is hard to undo once code depends on it. The option easiest to reverse was chosen.
Decision (to be detailed in `docs/spec/ctrl.md`): one command per valid/ready transfer as a packed struct with named fields (`op` 2 bits: LOAD_W, LOAD_A, COMPUTE, STORE; `mem_addr`, `mem_stride` 32 bits; `buf_addr`, `rows`; `acc_mode` 1 bit), defined once in an SV package and mirrored by one Python encoder (`sysarray/commands.py`) that both the compiler and the testbench use. No binary file format beyond a list of these fields (hex dump optional).
Alternatives: a 64-bit packed instruction word (smaller, but fixed bit positions are harder to change); separate per-block ports (what M6b uses; leaks sequencing rules to the user).
Consequences: Changing a field changes one SV package and one Python dataclass; both are tested against each other.

## D-022 Timing work goes into its own milestone (M7b) before the controller
Date: 2026-11-12 · Status: PROPOSED · Milestone: M7
Context: M7 measured 66.75 MHz for `sa_array` S = 8 (PE MAC path, routing-limited) and 60.55 MHz for `sa_core` (input-buffer BRAM → PE(0,0) MAC in one cycle) — `results/synth/sa_array_S8_0c93383.json`, `sa_core_S8_0c93383.json`. Fixing either changes cycle constants (array latency 2S − 1, feeder timing, the reload and STORE rules) that M8's controller will encode.
Decision: Insert M7b before M8: (1) register the buffer → array path (feeder output register), (2) evaluate a pipeline register between the multiply and the add in the PE (latency +1 per PE row → array latency changes), tests and specs first, re-measure latency (`make measure-latency`) and synthesis (`make synth`) before/after.
Alternatives: Leave timing for after the MVP (simpler, but every later number would be at ~60 MHz and the controller would need rework); pipeline only the BRAM path (cheap, fixes `sa_core`'s worst path, leaves the array at ~67 MHz).
Consequences: M8 is revised after M7b with the new constants. The BRIEF's M7 exit ("before/after if pipelined") is met in M7b.

## D-023 Stop timing work at ~83–85 MHz for the MVP
Date: 2026-11-12 · Status: PROPOSED · Milestone: M7b
Context: After M7b, `sa_core` S = 8 reaches 82.38–85.22 MHz over 3 seeds (`results/synth/sa_core_S8_d4aedec*.json`), limited by the accumulator's BRAM read → 32-bit add → BRAM write; `sa_array` reaches 83.68–86.39 MHz, limited by routing between the DSP columns and fabric FFs.
Decision: Keep the current design for the MVP. The next timing step — use the DP16KD output register (or a fabric register) on the accumulator read and move the add one cycle later — changes the accumulator RMW timing and the STORE rule, so it is listed as a candidate for after M11 (inside MVP scope, not an extension) and not done now.
Alternatives: Continue timing work now (delays the controller/compiler, which the MVP needs more); a deeper PE pipeline (adds latency, and the array is routing-limited, not logic-limited).
Consequences: Reported numbers use these Fmax values; the README will name the accumulator path as the limiter.

## D-024 COMPUTE after COMPUTE waits for the previous COMPUTE's last accumulator write
Date: 2026-11-12 · Status: PROPOSED · Milestone: M8
Context: M8's random command programs found a real design hazard: `sa_acc` latches mode/base when the feeder accepts a STREAM, but the previous COMPUTE's outputs keep arriving for 2S cycles after its `done` (array latency) and are written one cycle later. A COMPUTE issued right after another changed the configuration under the in-flight rows (regression test `tb/top` `test_back_to_back_compute`).
Decision: The controller holds a COMPUTE's feeder start until `now ≥ last COMPUTE done + 2S + 1` (`docs/spec/acc.md` §2 rule 3, `docs/spec/ctrl.md` §2). In tiled GEMMs a LOAD_A sits between COMPUTEs, so the wait is normally already covered.
Alternatives: Carry the accumulator row address and mode with the data (a (8+1)-bit tag delayed 2S cycles next to the array, 144 FFs at S = 8): no bubble for back-to-back COMPUTEs, but changes `sa_acc`/`sa_core` and their tests; a 1-deep config queue in `sa_acc` (insufficient: with 1-row COMPUTEs up to three can be in flight at S = 8).
Consequences: Back-to-back COMPUTEs cost up to ~2S idle cycles; the predictor (M9) must model the gap.

## D-025 Padding is done by the host in memory; predictor assumes a non-stalling memory
Date: 2026-11-12 · Status: PROPOSED · Milestone: M9
Context: BRIEF §7.1 asks for zero padding of partial tiles; the hardware has no zero-fill path.
Decision: `sysarray.tile()` lays out zero-padded copies of A (M × Kp) and B (Kp × Np) in the memory image; C is read back from C_pad (M × Np) and cropped. Padded MACs count as issued, not useful. `sysarray.predict()` replays the controller timing for a memory that accepts one read per cycle with fixed latency L and never stalls; under that assumption it matches the hardware counters exactly (tb/gemm), and with stalls the hardware is slower.
Alternatives: zero-fill in the DMA (no host copy, but new RTL); predicting with a stochastic memory model (no exact check possible).
Consequences: Memory traffic includes padded bytes; M11 reports useful vs issued MACs separately.

## D-026 SCALE-Sim comparison on the shapes it finishes
Date: 2026-11-13 · Status: PROPOSED · Milestone: M11
Context: SCALE-Sim v3 (PyPI `scalesim` 3.0.0, needs NumPy ≤ 2.2 in its own venv) did not finish sq256 within 25 minutes, and a run with all ten BRIEF shapes was still going after more than 30 CPU-minutes.
Decision: Commit SCALE-Sim results for sq8, sq16, sq64 and odd only, state exactly what ran (`results/scalesim/COMPARISON.md`), and compare the large shapes through the roofline and the exact predictor instead.
Alternatives: Run SCALE-Sim for hours in a later session (possible, no design change); a SCALE-Sim config with larger SRAMs to speed it up (would no longer mirror SysArray).
Consequences: The BRIEF's "SCALE-Sim comparison" deliverable is partial; listed under limitations in the README.

## D-027 PE product register mapped onto the MULT18X18D output register (behavioural model for simulation)
Date: 2026-11-13 · Status: PROPOSED · Milestone: M11b
Context: M7b's two-stage MAC put `prod_q` in fabric FFs after the DSP; nextpnr routed every product out of the DSP and back, and `sa_array` was routing-limited (86.39 MHz, `results/synth/sa_array_S8_d4aedec.json`).
Decision: Under `` `ifdef SA_ECP5_DSP `` (set only by `scripts/synth/ecp5.py`) `sa_pe` instantiates `MULT18X18D` with `REG_OUTPUT_CLK = CLK0` and a synchronous output reset driven by `!a_valid_in`; otherwise the same register is plain `always_ff`. Simulation of the DSP form uses `tb/models/MULT18X18D.v`, a behavioural model written here from the Lattice primitive's documented parameters; tb/pe and tb/array run both forms.
Alternatives: keep fabric `prod_q` (simpler, slower); rely on Yosys to absorb the register into the DSP (it did not with Yosys 0.69).
Consequences: `sa_array` 112.99 MHz, `sa_pe` 191.13 MHz (`results/synth/*_c64045a.json`). Risk: the sim model is ours, not Lattice's; the RTL equivalence of the two forms is tested, the mapping to real silicon behaviour is not (needs a board or vendor sim model).
Update (M11c, 14 Nov 2026): the planned confidence check (post-synthesis netlist simulation with Yosys's own ECP5 cell library) is not possible: Yosys 0.69 ships `MULT18X18D` only as a black box in `share/yosys/ecp5/cells_bb.v`; `cells_sim.v` has no model for it (same in the Yosys 0.62 inside the LibreLane image). Per the plan no substitute model was written. The risk above stands; checking it needs Lattice's simulation library or a board.

## D-028 Controller safety checks kept although they limit `sa_top` to 84.63 MHz
Date: 2026-11-13 · Status: PROPOSED · Milestone: M11b
Context: Error 5 (read of never-written rows) needs a 256-bit and a 64-bit written-row bitmap checked against a row range per command. First synthesis of `sa_top` with it: 38.85 MHz (`results/synth/sa_top_S8_b54dd8b.json`). Two fixes (registered range masks at accept, `433f87e` → 75.2 MHz; bitmap update one cycle after CHECK, `7d6f36a` → 75.4, `c64045a` → 84.63 MHz) — the two-attempt budget for this fix is used.
Decision: Keep error 5 and 48-bit counters; `sa_top`'s limiter is now `buf_mask` → `upd_ibuf_q` in `sa_ctrl` (`results/synth/sa_top_S8_c64045a.json`), close to M7b's `sa_core` level.
Alternatives: drop error 5 (faster, loses a correctness check); a 2-cycle CHECK state (one more cycle per command, small cost for long COMPUTEs, cheapest next step).
Consequences: Listed as a remaining issue; M13 changes the controller anyway and can add the 2-cycle CHECK.
Update (M11c, 14 Nov 2026, option B, two attempts): attempt 1, a two-cycle CHECK (`CHECK` registers the error code, `DECIDE` acts on it): `sa_top` 84.02 MHz (`results/synth/sa_top_S8_dc61168.json`), no gain; the limiter moved to `buf_addr + rows` → overlap compare → dispatch → DMA. Attempt 2, `buf_end`/`acc_end` registered at accept: 92.89 MHz (`results/synth/sa_top_S8_ebfc542.json`, from 84.18). Both changes are kept together; the gain was measured only for the pair, not for each change alone. Cost: +1 cycle per command, utilization −0.0008 to −0.0087 on the `make perf` shapes (predicted (analytical) and measured, measured on the `make perf` shapes). Error 5 stays (never option C).

## D-029 LOAD_W `rows` = number of real weight rows
Date: 2026-11-13 · Status: PROPOSED · Milestone: M11b
Context: The host zero-padded B's last k-tile in memory, so the DMA fetched S rows even when only K mod S were real.
Decision: LOAD_W `rows` = r in 1…S−1 makes the DMA read r rows and the feeder present rows r…S−1 as zero (`rows` = 0 keeps meaning S; `rows` > S is error 2). The tiler sets r = K mod S on the last k-tile; funcsim and the predictor follow.
Alternatives: byte masks for column padding too (bigger DMA change, not done); leave host padding (D-025).
Consequences: weight traffic drops by (S − K mod S)·S bytes per partial tile; column padding of B and K padding of A still go through memory.

## D-030 Double buffering = concurrent dispatch + ping-pong input halves + per-row accumulator tags; shadow weights deferred
Date: 2026-11-13 · Status: PROPOSED · Milestone: M13
Context: Double buffering was approved as the first extension after the MVP. M13's plan listed shadow weight registers in every PE as well.
Decision: Build the smallest version that removes the measured limiter: `sa_ctrl` dispatches in order to two concurrent units (DMA, feeder) with explicit dependency checks (`docs/spec/ctrl.md` §2); the input buffer is used as two 128-row halves by compiler convention (no RTL split); the accumulator config travels with each row (2S-deep tag line), removing D-024's gap. Shadow weights are not built: the reload costs ≈ 2S − 5 + S + 3 cycles per k-tile (predicted (analytical) ≈ 26 of ≈ 285 at S = 8, M = 256).
Alternatives: shadow weights now (one more 8-bit register per PE, a swap flag travelling with the activations, a separate weight path in the feeder; larger change to the verified array); a hardware buffer split (fixed halves in RTL: less flexible than a compiler convention).
Consequences: `cmd_ready` returns one cycle after the unit start, `busy` covers in-flight units, the predictor models the two units; the next step for utilization is shadow weights and STORE overlap (STORE is exclusive with COMPUTE because the accumulator has one read port).

## D-031 Dispatcher timing: gate down-counters and delayed macs_issued
Date: 2026-11-13 · Status: PROPOSED · Milestone: M13
Context: The concurrent dispatcher put M8's 48-bit `now >= store_ok/reload_ok` compares in front of `state_q`: `sa_top` 84.63 → 71.07 MHz (`results/synth/sa_top_S8_931741d.json`).
Decision: Try 1: the gates are ⌈log2(2S + 4)⌉-bit down-counters loaded with GAP − 1 at a COMPUTE's done (76.37 MHz, `sa_top_S8_297a337.json`; next limiter CHECK → 48-bit `macs_q` add). Try 2: `macs_issued` is added one cycle after CHECK, like the bitmaps (84.18 MHz, `sa_top_S8_ea8fa1b.json`). Cycle behaviour unchanged (tb/top cycle table, tb/gemm exact predictor).
Alternatives: a 2-cycle CHECK (one more cycle per command); keep 71 MHz.
Consequences: `macs_issued` reaches its final value one cycle after the last COMPUTE's CHECK; the remaining limiter is the error-check path (D-028).

## D-032 SKY130 flow: LibreLane 3.0.17 in Docker, `sa_array` only, defaults except the clock and core utilization
Date: 2026-11-14 · Status: PROPOSED · Milestone: M12
Context: Brief objective 7 asks for area and slack on SKY130. The cloud session can pull `ghcr.io/librelane/librelane` and fetch the SKY130 PDK through ciel's FOSSi archive mirror, so the flow runs in the cloud (no `DEFERRED-LOCAL` step).
Decision: `scripts/librelane/run.py` runs LibreLane 3.0.17 with PDK `8afc8346…` (the version LibreLane pins), top `sa_array`, S = 8, `FP_CORE_UTIL` 40 %, LibreLane's default I/O constraint (20 % of the period on every port) and default sign-off (nine corners). Reported: area, cell counts, worst setup/hold slack over all corners and at `nom_tt_025C_1v80`, DRC/LVS/antenna, and `fmax = 1000 / (period − slack)` as a derived figure. A run that finishes place-and-route but fails sign-off is recorded with its error. Hold-repair margin raised only when a run fails hold.
Alternatives: LibreLane's Nix flake (needs GitHub access); `sa_core` (its 256-row buffers would become flip-flops without SRAM macros, so its area would not represent the design); tighter I/O constraints from a real chip context (none exists).
Consequences: SKY130 numbers describe the array alone, at the slow-corner sign-off LibreLane uses; ECP5 numbers in the README are for the full `sa_core`/`sa_top` as well, so the two tables are compared block by block (`sa_array`).

## D-033 SKY130 slew repair stops after three attempts; two runs reported, PNR corner change proposed
Date: 2026-11-16 · Status: PROPOSED · Milestone: M12b
Context: The 12,787 max-slew violations of run 4 were not accepted (`results/asic/sa_array_S8_0d8ca14_15ns_io30.json`). Diagnosis: 12,706 of 12,771 violating pins at max_ss are driven by `clkdlybuf4s25_1` fanout buffers (fanout ≈ 10) inserted by LibreLane's placement repair; post-route design repair is off by default and slew is only a warning. The budget was at most three attempts at S = 8, 15 ns, I/O 30 %.
Decision: Attempts: (1) exclude `clkdlybuf4s*`, post-route repair on → 14,831 (repair switched to `clkbuf_1`/`buf_1`); (2) also exclude `buf_1`/`clkbuf_1`, repair slew margins 40/30 % → 113, setup −0.764 ns at ss; (3) post-route margin 40 % and post-route setup repair → 91, setup −0.453 ns at ss (7 endpoints). Report run 4 (timing met, 12,787 violations) and run 8 (91 violations, setup fails at ss) side by side; no run is called clean. `run.py` gained `--set/--tag`; `scripts/librelane/slew_diag.py` groups violations by driver and source.
Alternatives: a fourth attempt with `PNR_CORNERS` set to the slow corners, so LibreLane's timing and design repair optimise where sign-off fails (its mid-flow STA and timing repair use only `nom_tt` by default, where run 8 has +5.006 ns); a longer clock period (run 8's slack-derived worst-corner clock is 64.71 MHz); `MAX_FANOUT_CONSTRAINT` below 10.
Consequences: The SKY130 result stays "not fully clean" until a further attempt succeeds; recommended next step: `PNR_CORNERS` = slow corners (≈ 1 h run).

## D-034 Published copy: a clean public repository built from this one
Date: 2026-11-22 · Status: DECIDED · Milestone: after M15
Context: The development repository holds planning, progress and review files, AI-assistant configuration and personal notes next to the design. The public repository should hold only the design, its tests, docs and results, read as one author's work, and still build and pass its tests on its own.
Decision: The public repository (`Fe3w/systolic-array-gemm-accelerator`) is rebuilt from this one by a publishing script, never edited by hand. It removes a fixed list of private paths (plans, cycle log, status, review sheets, personal notes, assistant files, cloud-session helpers, the resume-metrics generator), refuses to publish if private text, secrets, unexpected top-level files or files over 5 MB are present, runs lint, the Python and script tests (including the demo simulations) and the docs check on both copies, and commits as the author with a fresh history. Design docs that were public-facing in substance (the technical brief, this log, the results index) stay public with process wording made neutral; engineering rules move to `docs/CONVENTIONS.md`. Decisions previously marked as chosen under delegated authority are recorded as `PROPOSED`.
Alternatives: Make this repository public as is (exposes planning and assistant files; old commit trailers); a hand-maintained public branch (drifts, easy to leak); `git filter-repo` on the full history (rewrites history, still needs per-file decisions).
Consequences: Result files keep the commit SHAs of this repository, which the public history does not contain; `docs/RESULTS.md` says so and `compiler/tests/test_results_provenance.py` skips only the commit-existence check outside this repository (the index check still runs). README and public docs must link only to public files: publishing runs the docs check on the clean copy and fails on dead links; the CI publish check fails on private paths and text.
