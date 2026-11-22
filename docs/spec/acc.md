# Spec: accumulator `sa_acc` and core `sa_core`

Status: written in M6b before the RTL. Decisions: D-016 (256 rows × S int32),
D-017 (SRAM semantics), D-004a (wrap). Cycle counts **predicted (analytical)**
until the tests assert them.

## 1. `sa_acc #(S, ACC_W, ACC_DEPTH)`

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk`, `rst` | in | 1 | |
| `c_valid`, `c_row` | in | 1, S × ACC_W | from `sa_array` |
| `c_mode` | in | 1 | (M13) this row's mode: 0 = OVERWRITE, 1 = ACCUMULATE |
| `c_addr` | in | AA_W | (M13) this row's accumulator address |
| `st_re`, `st_raddr` | in | 1, AA_W | STORE read port (from `sa_dma` `src_*`) |
| `st_rdata` | out | S × ACC_W | 1-cycle read data, holds while no read |

Read-modify-write pipeline, output row arriving in cycle t with its tag
(M13; before M13 a `cfg_*` port latched mode and base per COMPUTE, D-024),
p = `c_addr`:

| Cycle | OVERWRITE | ACCUMULATE |
| --- | --- | --- |
| t | capture `c_row`, p, mode | also read row p |
| t + 1 | (pipeline) | register the BRAM read data (M11b) |
| t + 2 | write `c_row` to p | write old[p] + `c_row` (per element, ACC_W wrap) to p |

* Same-row rule: an ACCUMULATE row must arrive ≥ 3 cycles after the previous
  row to the same address (its write is in t + 2, the SRAM is read-first).
  Rows of one COMPUTE have distinct addresses.
* Across COMPUTEs (feeder spec §4.2 and array latency 2S): the next
  COMPUTE's first `c_valid` is at least 3 cycles after the previous last
  `c_valid` (4 since the M7b output register), whose write lands 1 cycle after it, so a new read never races a
  pending write, even with the same rows (K-slice accumulation).
* Read port sharing: the SRAM read address is the RMW address when the RMW
  reads, else `st_raddr`; `st_rdata` is the SRAM's `rdata`. **Rule:** a
  STORE must not run while outputs of a COMPUTE are still arriving
  (sequenced by the tests now, by the controller in M8).

Reset: the pipeline valid bit only. Contents not reset (OVERWRITE initializes).

## 2. `sa_core #(S, IN_DEPTH, ACC_DEPTH, MA_W)` (structural)

`sa_dma` + weight buffer + input buffer + `sa_feeder` + `sa_array` +
`sa_acc`. The DMA writes the buffers (LOAD) and reads the accumulator
(STORE, `src_*` → `st_*`); the feeder reads the buffers. Ports: the memory
channels, the DMA descriptor (`dma_*`), the feeder command (`f_start`,
`f_op`, `f_base`, `f_rows`, `f_busy`, `f_done`, `f_dropped`) and the
accumulator config `acc_mode`, `acc_base`, latched when the feeder accepts a
STREAM (`f_start && !f_busy && f_op == STREAM`). M13: the latched config
becomes a per-row tag {mode, base + j} next to each `a_valid` (a counter
advances per row) and travels through an `sa_reg` delay line of D = 2S (the
array latency) to `c_mode`/`c_addr`, so it arrives with the row's `c_valid`.
A new STREAM is accepted only after the previous one's last `a_valid`, so the
latch never changes under a row of the previous STREAM. Cost: (AA_W + 1) × 2S
flip-flops (144 at S = 8, predicted).

Sequencing rules for users of `sa_core` (the M8 controller automates them):
1. LOAD_W of the next tile no earlier than the array reload rule
   (`docs/spec/array.md` §3 rule 3): feeder `start` ≥ t_last + 2S − 5, with
   t_last = the cycle of the previous STREAM's `done` (= its last `a_valid`;
   the first `w_load` comes 3 cycles after `start` since M7b, so
   start + 3 ≥ t_last + 2S − 2).
2. STORE of rows written by a STREAM no earlier than its last accumulator
   write: STREAM `done` in cycle d → last `c_valid` d + 2S (two-stage MAC,
   M7b) → last write d + 2S + 2 (3-stage RMW, M11b) → STORE `start` ≥ d + 2S + 3 (its first source read is one cycle
   later).

3. COMPUTE after COMPUTE (D-024, removed in M13): with per-row tags the next
   COMPUTE may start as soon as the feeder is free (done + 1). Its first row
   reaches the accumulator ≥ 4 cycles after the previous last row, which
   satisfies the same-row rule of §1.

## 3. Tests

`tb/acc/` (`sa_acc`, S ∈ {4, 8}): OVERWRITE rows then read back; ACCUMULATE
two and three passes over the same rows; int32 wrap; back-to-back rows every
cycle; a new COMPUTE at the closest spacing (3 cycles) to the same rows.

`tb/core/` (`sa_core`, S ∈ {4, 8}, memory model with stalls): one tile
(M ∈ {1, 8, 37}) memory → buffers → array → accumulator → memory; a
two-K-slice GEMM (K = 2S) with ACCUMULATE; C compared with `golden.gemm`
for the whole matrix in memory.
