# Spec: buffers `sa_sram`, sequencer `sa_feeder`, test top `sa_feed_top`

Status: written in M5 before the RTL; M7b added the feeder output register
(D-022): every array input now comes one cycle later than in M5 (§3, §4). Decisions: D-016 (sizes), D-017 (SRAM
semantics), D-014/D-015 (array interface and reload rule). Cycle counts here
are **predicted (analytical)** until the M5 tests assert them.

## 1. `sa_sram #(WIDTH, DEPTH)` — behavioural 1R1W memory (D-017)

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk` | in | 1 | clock |
| `we` | in | 1 | write `wdata` to `waddr` at this edge |
| `waddr` | in | ADDR_W | write address, ADDR_W = max(1, ⌈log2 DEPTH⌉) |
| `wdata` | in | WIDTH | write data |
| `re` | in | 1 | read `raddr` at this edge |
| `raddr` | in | ADDR_W | read address |
| `rdata` | out | WIDTH | registered: `mem[raddr]` from the edge where `re` was high |

* Read latency 1: `re` in cycle t → `rdata` valid in cycle t + 1. `rdata`
  holds its value while `re = 0`.
* Read-during-write to the same address in the same cycle returns the
  **old** contents (read-first). The new contents are visible to a read one
  cycle later.
* No reset: contents and `rdata` are undefined until written/read.
* Addresses ≥ DEPTH are out of range; the sequencer never generates them, and
  the tests never write them (behaviour unspecified).

## 2. Buffers (D-016)

| Buffer | Instance | WIDTH | DEPTH | Row layout |
| --- | --- | --- | --- | --- |
| Weight | `u_wbuf` | S × 8 | S | row k = B[k0 + k][n0 .. n0+S−1], element 0 in the low byte |
| Input | `u_ibuf` | S × 8 | `IN_DEPTH` (256) | row m = A[m][k0 .. k0+S−1], element 0 in the low byte |

The row layout equals the packed `w_row`/`a_row` layout of `sa_array`, so a
buffer row goes to the array unchanged.

## 3. `sa_feeder #(S, IN_DEPTH)` — runs one command at a time

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk`, `rst` | in | 1 | clock; synchronous active-high reset |
| `start` | in | 1 | command request, accepted only when `busy = 0` |
| `op` | in | 1 | 0 = LOAD_W, 1 = STREAM |
| `base` | in | IA_W | STREAM: first input-buffer row (IA_W = ⌈log2 IN_DEPTH⌉) |
| `rows` | in | IA_W + 1 | STREAM: number of rows, 1 … IN_DEPTH (0 = no rows, done only) |
| `busy` | out | 1 | a command is running (registered) |
| `done` | out | 1 | one-cycle pulse: the command's last array input is presented this cycle |
| `start_dropped` | out | 1 | one-cycle pulse: `start` arrived while `busy` and was ignored |
| `wb_re`, `wb_raddr` | out | 1, WA_W | weight buffer read port |
| `wb_rdata` | in | S × 8 | weight buffer read data |
| `ib_re`, `ib_raddr` | out | 1, IA_W | input buffer read port |
| `ib_rdata` | in | S × 8 | input buffer read data |
| `w_load`, `w_row` | out | 1, S × 8 | to `sa_array` |
| `a_valid`, `a_row` | out | 1, S × 8 | to `sa_array` |

Behaviour:
* **LOAD_W** reads weight rows S−1, S−2, …, 0 (one per cycle) and presents
  each to the array as `w_load = 1`, `w_row` **two** cycles after its read
  (the array wants B[k0+S−1] first, `docs/spec/array.md` §3 rule 1).
* **LOAD_W with `rows` = r in 1…S−1** (M11b): rows r…S−1 are presented as zero
  (`wreal_q`, a zero flag aligned with the read), so stale buffer rows never
  reach the array; the DMA reads only r rows.
* **STREAM** reads input rows `base` … `base + rows − 1` and presents each as
  `a_valid = 1`, `a_row` two cycles after its read.
* Output register (M7b, D-022): `w_row`/`a_row` are the buffer's `rdata`
  registered once more in the feeder, and `w_load`/`a_valid` the in-flight bit
  delayed by the same stage. M7 measured the unregistered path (BRAM
  clock-to-out → PE(0,0) multiply → add) as `sa_core`'s critical path
  (`results/synth/sa_core_S8_0c93383.json`).
* The feeder does **not** enforce the reload rule (D-015) or "no compute
  during load"; the controller (M8) sequences commands. It only guarantees
  that one command's array inputs are contiguous and in order.
* `start` with `busy = 1` is ignored and pulses `start_dropped`.

FSM (registered state):

```
IDLE --start && !busy--> RUN (latch op, next address, remaining count)
RUN: issue one read per cycle while remaining > 0; after the last read -> IDLE
busy = (state == RUN) || inflight_q || out_valid_q
```

## 4. Cycle tables (predicted)

Cycle numbering as in `docs/spec/array.md`: inputs presented in cycle t are
captured at the edge ending cycle t.

### 4.1 LOAD_W (S = 4), `start` in cycle 0

| Cycle | state | `wb_re` / addr | `w_load` / `w_row` | `busy` | `done` |
| --- | --- | --- | --- | --- | --- |
| 0 | IDLE | – | 0 | 0 | 0 |
| 1 | RUN | 1 / 3 | 0 | 1 | 0 |
| 2 | RUN | 1 / 2 | 0 | 1 | 0 |
| 3 | RUN | 1 / 1 | 1 / B[3] | 1 | 0 |
| 4 | RUN | 1 / 0 | 1 / B[2] | 1 | 0 |
| 5 | IDLE | – | 1 / B[1] | 1 | 0 |
| 6 | IDLE | – | 1 / B[0] | 1 | **1** |
| 7 | IDLE | – | 0 | 0 | 0 |

`w_load` in cycles 3 … S + 2; `done` in cycle S + 2; the next `start` is
accepted in cycle S + 3 (busy = 0).

### 4.2 STREAM of M rows from `base`, `start` in cycle 0

`a_valid` in cycles 3 … M + 2 (row base + j in cycle 3 + j); `done` in cycle
M + 2; next `start` accepted in cycle M + 3. With the array's latency 2S
(two-stage MAC, M7b; `docs/spec/array.md` §4.2), output row j appears with
`c_valid` in cycle 3 + j + 2S, the last one in cycle **M + 2S + 2** (S = 8,
M = 64: cycle 82).

### 4.3 LOAD_W then STREAM, back to back

LOAD_W `start` in cycle 0, STREAM `start` in cycle S + 3 (earliest). Last
`w_load` in cycle S + 2, first `a_valid` in cycle S + 6: three idle cycles
between them, so "no compute during load" holds. Last `a_valid` in cycle
M + S + 5, last output in cycle M + S + 5 + 2S = M + 3S + 5. Total from
LOAD_W `start` to the cycle after the last output: **M + 3S + 6** cycles
(S = 8, M = 64: 94; M + 3S + 3 in M5), versus the bare array's T_tile =
M + 3S (two-stage MAC): +3 cycles before the first `w_load` (decode, SRAM
read, output register) and +3 idle cycles between the last `w_load` and the
first `a_valid`.

### 4.4 STREAM with `rows = 0`

`start` in cycle 0 → RUN in cycle 1 with remaining = 0 → no read, `done` in
cycle 1, IDLE in cycle 2; no `a_valid`.

## 5. Reset

| Register | Reset? |
| --- | --- |
| feeder `state`, `inflight_q`, `out_valid_q`, `start_dropped` | yes |
| feeder output data `w_row`/`a_row` registers | no |
| feeder address, count, op | no (written on `start`) |
| SRAM contents and `rdata` | no |

## 6. `sa_feed_top` (test top) and test list

`sa_feed_top` = `u_wbuf` + `u_ibuf` + `sa_feeder` + `sa_array`, exposing the
two buffer write ports, the command ports and the array outputs (`c_valid`,
`c_row`), plus `busy`, `done`, `start_dropped`.

`tb/sram/` (`sa_sram`, WIDTH 16, DEPTH 8 and 256):
1. Random writes then reads match a Python model; read latency exactly 1.
2. Read-during-write to the same address returns the old data; next read the
   new data.
3. `rdata` holds while `re = 0`.

`tb/feed/` (`sa_feed_top`, S = 4 and 8):
1. LOAD_W cycle table §4.1: `done`/`busy` cycles exact; weights reach the
   array (checked through a following STREAM).
2. LOAD_W + STREAM with M ∈ {1, 8, 64, 256}: outputs match golden, last
   output in the cycle of §4.3.
3. STREAM from a non-zero `base`, and `rows = 0`.
4. Two tiles: LOAD_W, STREAM, (wait for the reload rule), LOAD_W, STREAM.
5. `start` while busy: ignored, `start_dropped` pulses, the running command
   is unaffected.
