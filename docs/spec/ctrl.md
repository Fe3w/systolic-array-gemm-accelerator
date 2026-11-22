# Spec: command interface (`sa_pkg`), controller `sa_ctrl`, top `sa_top`

Status: written in M8 before the RTL. Decisions: D-021 (command struct in an
SV package + Python mirror), D-016 (depths 256), the sequencing rules of
`docs/spec/acc.md` §2 (M7b constants). Cycle counts are **predicted
(analytical)** until the M8 tests assert them.

## 1. Command (`rtl/ctrl/sa_pkg.sv`, mirrored by `compiler/sysarray/commands.py`)

One command per valid/ready transfer on `cmd` (`cmd_valid`/`cmd_ready`).
Packed struct, fields MSB first (93 bits):

| Field | Bits | LOAD_W | LOAD_A | COMPUTE | STORE |
| --- | --- | --- | --- | --- | --- |
| `op` | 3 | 0 | 1 | 2 | 3 (4…7 = unknown → error) |
| `acc_mode` | 1 | – | – | 0 OVERWRITE / 1 ACCUMULATE | – |
| `mem_addr` | 32 | B tile row 0 | first A row | – | first C row |
| `mem_stride` | 32 | bytes between B rows | bytes between A rows | – | bytes between C rows |
| `rows` | 9 | real weight rows: 0 = S, 1…S−1 = partial tile, rest zero (M11b) | rows (1…256) | rows (1…256) | rows (1…256) |
| `buf_addr` | 8 | – | first input-buffer row | first input-buffer row | first accumulator row |
| `acc_addr` | 8 | – | – | first accumulator row | – |

Semantics (the Python functional model in the tests implements exactly this):
- LOAD_W: the array's weights become the S × S int8 tile at `mem_addr`
  (row k at `mem_addr + k·mem_stride`); with `rows` = r in 1…S−1 only rows
  0…r−1 are read and rows r…S−1 are zero (M11b, padding traffic).
- LOAD_A: input-buffer row `buf_addr + i` ← memory row `mem_addr + i·mem_stride`.
- COMPUTE: accumulator row `acc_addr + i` ← (ACCUMULATE ? old : 0) +
  input-buffer row `buf_addr + i` × weights, i = 0 … rows−1 (int32 wrap).
- STORE: memory row `mem_addr + i·mem_stride` (S int32, little-endian) ←
  accumulator row `buf_addr + i`.

Errors (sticky `err`, `err_code`; the command is dropped, nothing runs, the
controller returns to IDLE and accepts the next command; `err_clear` clears):

| Code | Condition |
| --- | --- |
| 1 | unknown `op` (4…7) |
| 2 | `rows` = 0 or `rows` > 256 (LOAD_A, COMPUTE, STORE); LOAD_W `rows` > S |
| 3 | `buf_addr + rows` > 256, or COMPUTE `acc_addr + rows` > 256 |
| 4 | COMPUTE before any LOAD_W since reset |
| 5 | (M11b) COMPUTE reads input-buffer rows no LOAD_A wrote, ACCUMULATE into or STORE of accumulator rows no COMPUTE wrote (written-row bitmaps, cleared by reset) |

When several apply, the lowest code is reported.

## 2. `sa_ctrl` dispatcher (M13: DMA and feeder run concurrently)

M8–M11b ran one command at a time. Since M13 an in-order dispatcher hands
each command to its unit and accepts the next command one cycle later; the
DMA (LOAD_A, STORE, LOAD_W's transfer) and the feeder (COMPUTE, LOAD_W's
array load) run concurrently.

```
IDLE --accept--> CHECK --> DECIDE --error--> IDLE
                                  --ok-----> ISSUE --unit start--> IDLE
                                                   (LOAD_W: --DMA start--> FEED_W --feeder start--> IDLE)
```

- `cmd_ready = (state == IDLE)`; `busy` = not IDLE, or a unit in flight.
- A unit is *in flight* from its `start` to its `done`, and free one cycle
  after `done` (`dma_act_q`, `f_act_q`, with the command's kind and input-buffer
  row range). In ISSUE the start is held until the unit is free and:

| Command | Waits while (the other unit) | Also |
| --- | --- | --- |
| LOAD_A | a COMPUTE streams overlapping input rows (WAR) | – |
| STORE | any COMPUTE is in flight (accumulator read port, RAW) | `now ≥ store_ok_q` = last COMPUTE done + 2S + 3 |
| LOAD_W (DMA) | a LOAD_W is still on the feeder (it reads the weight buffer) | – |
| LOAD_W (feeder, FEED_W) | its own DMA in flight | `now ≥ reload_ok_q` = last COMPUTE done + max(0, 2S − 5) |
| COMPUTE | a LOAD_A writes overlapping input rows (RAW), or a STORE runs (WAR on the accumulator, shared read port) | – (no gap after a COMPUTE: per-row tags, `docs/spec/acc.md` §2) |

- Program order is the semantics (§1): a command never overtakes an earlier
  one, and every pair touching the same storage is ordered by a row above.
  Errors and the written-row bitmaps are evaluated in CHECK, in program order;
  the error code is registered and acted on one cycle later in DECIDE (M11c,
  D-028), which keeps the 256-bit written-row check off the paths into the
  state and error registers. Error 4 is set by an earlier LOAD_W's DECIDE.
- Double buffering is a compiler convention: the tiler alternates LOAD_As
  between rows 0–127 and 128–255, so the next LOAD_A has no WAR with the
  running COMPUTE (`compiler/sysarray/tiler.py`).
- `now` is a free-running 48-bit cycle counter.

## 3. Cycle tables (always-ready memory, read latency L; command accepted in cycle t, units free)

| Command | Unit `start` in | Unit `done` in | `cmd_ready` again |
| --- | --- | --- | --- |
| LOAD_A, R rows | DMA: t + 3 | t + 3 + R + L | t + 4 |
| LOAD_W | DMA: t + 3; feeder: d + 1 where d = DMA done | feeder: d + 1 + S + 2 | d + 2 |
| COMPUTE, R rows | feeder: t + 3 | t + R + 5 | t + 4 |
| STORE, R rows (no gate) | DMA: t + 3 | t + 3 + 4R + 1 | t + 4 |

(cycle t + 1 is CHECK, t + 2 is DECIDE since M11c; M13 started units at t + 2.) With waits, the start moves to the first cycle in
which the conditions of §2 hold, and `cmd_ready` returns one cycle after it.
`sysarray.predict` replays exactly this and matches the hardware counters for
an always-ready memory (tb/gemm).

Steady state of a double-buffered k-tile (S = 8, two 128-row chunks, order A),
predicted (analytical), cycles relative to the first COMPUTE's start c:

| Cycle | DMA | Feeder |
| --- | --- | --- |
| c … c + 130 | LOAD_A (other half), 128 + L | COMPUTE chunk 0, done c + 130 |
| c + 131 … | – | COMPUTE chunk 1 (if its LOAD_A is done) |
| … + 131 … | LOAD_A (next k-tile, half 0), LOAD_W DMA (S + L) | |
| done₁ + 11 … + 21 | – | LOAD_W feeder (reload gate 2S − 5, then S + 2) |

So a k-tile costs ≈ 2 × 131 + 2S + 7 ≈ 285 cycles for 256 rows (≈ 0.9 of
peak); STOREs (4 cycles per row, exclusive with COMPUTE) add ≈ 4M per column
strip. `sysarray.predict` gives 0.7862 for sq256 (test_tiler).

## 4. Performance counters (48-bit since M11b, cleared by `rst`)

| Counter | Definition |
| --- | --- |
| `cycles_total` | (cycle of the last STORE's DMA `done`) − (cycle of the first accepted command) + 1; 0 before the first STORE completes |
| `cycles_dma` | cycles with the DMA `busy` |
| `cycles_compute` | cycles with the feeder `busy` |
| `macs_issued` | S² × Σ rows over accepted (error-free) COMPUTE commands |

`useful_macs` (BRIEF §9.1) is computed by the compiler (padding excluded);
`macs_issued` counts what the hardware issued, padding included.

## 5. `sa_top #(S)`

`sa_ctrl` + `sa_core` (IN_DEPTH = ACC_DEPTH = 256). Ports: `cmd_*`, memory
channels, `err`, `err_code`, `err_clear`, `busy` (= not IDLE), counters.

## 6. Tests (`tb/top/`, S ∈ {4, 8}, memory model with stalls)

1. Random valid command streams (≥ 200 commands per seed, all 16 ordered
   command pairs must occur; coverage asserted) against the Python functional
   model; final memory compared.
2. GEMMs (M, K, N multiples of S) as command lists, C vs `golden.gemm`.
3. Each error code: flag + code set, command dropped (memory and later results
   unaffected), no hang, `err_clear` works, the next command runs.
4. Counters: `macs_issued` exact; `cycles_dma`, `cycles_compute` equal the
   testbench's own count of the unit `busy` signals; `cycles_total` equals the
   testbench's (last STORE DMA done − first accept + 1).
5. Cycle table §3 with an always-ready memory for each command alone.
6. COMPUTE directly after COMPUTE (different rows, modes, bases) — the
   regression for D-024.
7. (M13) Overlap: a LOAD_A into the other half starts before the running
   COMPUTE's done. Hazards: RAW/WAR on input rows, LOAD_W while weights stream,
   STORE after COMPUTE, COMPUTE into rows a STORE reads — with and without
   memory stalls, memory equal to the functional model.
