# Spec: memory channels, memory model and `sa_dma`

Status: written in M6 before the RTL. Decisions: D-019 (bus = one input row
per beat), D-017 (SRAM semantics), D-016 (sizes). Cycle counts are
**predicted (analytical)** until the M6 tests assert them.

## 1. Memory channels (valid/ready, docs/CONVENTIONS.md)

Beat = BUS_W = S × 8 bits (S bytes; 8 at S = 8). Byte addresses; every
request address is a multiple of S. Little-endian: byte i of a beat is bits
[8i +: 8]. A transfer happens at a rising edge where `valid && ready`.
`valid` never depends combinationally on `ready`; while `valid && !ready`,
the payload stays stable and `valid` stays high.

| Channel | Direction (DMA view) | Payload |
| --- | --- | --- |
| read request | DMA → memory: `rd_req_valid`, ← `rd_req_ready` | `rd_req_addr` |
| read response | memory → DMA: `rd_resp_valid`, → `rd_resp_ready` | `rd_resp_data` (in request order) |
| write request | DMA → memory: `wr_req_valid`, ← `wr_req_ready` | `wr_req_addr`, `wr_req_data` (full beat) |

`sa_dma` ties `rd_resp_ready = 1`: every response is written into a buffer in
the cycle it arrives (an SRAM write port accepts one row per cycle).

## 2. Memory model (`tb/common/memory.py`, Python, cycle-stepped)

* `Memory(size, beat_bytes, read_latency=L ≥ 1, max_outstanding, rng,
  req_stall, resp_stall, wr_stall)`.
* `step(dut_outputs) -> dut_inputs` is called once per cycle with the DMA's
  outputs for that cycle and returns the memory's outputs for the same cycle
  (`rd_req_ready`, `rd_resp_valid`, `rd_resp_data`, `wr_req_ready`). The
  edge then performs the handshakes the two sides agreed on.
* A read request accepted in cycle c becomes eligible as a response in cycle
  c + L. Responses leave in order. With stalls enabled, the model may withhold
  `rd_resp_valid` for a cycle (only before it has raised it for that
  response), and randomly drop `rd_req_ready` / `wr_req_ready`.
* `rd_req_ready = 0` while `max_outstanding` reads are in flight.
* Writes update the byte array at the edge of the handshake.
* The model itself obeys §1 (never retracts a raised `rd_resp_valid`).

## 3. `sa_dma #(S, DATA_W, ACC_W, IN_DEPTH, ACC_DEPTH, MA_W = 32)`

Descriptor (accepted when `start && !busy`; `start` while busy is ignored and
pulses `start_dropped` in the next cycle):

| Field | Width | Meaning |
| --- | --- | --- |
| `dir` | 1 | 0 = LOAD (memory → buffer), 1 = STORE (source → memory) |
| `target` | 1 | LOAD only: 0 = weight buffer, 1 = input buffer |
| `mem_addr` | MA_W | byte address of row 0 (multiple of S) |
| `mem_stride` | MA_W | bytes between consecutive rows (multiple of S) |
| `rows` | BA_W + 1 | number of rows (0 = nothing, `done` only) |
| `buf_addr` | BA_W | first buffer / source row |

BA_W = max(⌈log2 IN_DEPTH⌉, ⌈log2 ACC_DEPTH⌉), so one field serves the input
buffer (LOAD) and the accumulator/source (STORE); the weight buffer uses the
low ⌈log2 S⌉ bits.

Other ports: `busy`, `done` (one-cycle pulse); buffer write ports
`wb_we/wb_waddr/wb_wdata`, `ib_we/ib_waddr/ib_wdata`; STORE source read port
`src_re/src_raddr/src_rdata` (S × ACC_W bits, 1-cycle latency, `src_rdata`
holds while `src_re = 0` — true for `sa_sram`).

**LOAD.** Requests rows at `mem_addr + i·mem_stride`, i = 0 … rows−1, one per
accepted handshake. Response i (in order) is written to buffer row
`buf_addr + i` in the cycle it arrives (`*_we` = `rd_resp_valid`). `done`
pulses in the cycle of the last response.

**STORE.** Row i is read from the source at `buf_addr + i` and sent as
BEATS = ACC_W / DATA_W = 4 beats to `mem_addr + i·mem_stride + b·S`,
b = 0 … 3 (beat b = bits [b·BUS_W +: BUS_W] of the row: little-endian int32
elements, element 0 first). The next row is read in the cycle the current
row's last beat is accepted, so beats of consecutive rows follow without a
gap. `wr_req_valid` is a register (`row_valid_q`), set after a source read and
cleared after the last beat's handshake unless the next row was read in the
same cycle. `done` pulses in the cycle the last beat is accepted.

FSM: IDLE → RUN on accept; RUN → IDLE in the `done` cycle. `busy` =
(state == RUN).

## 4. Cycle tables (always-ready memory, `start` in cycle t)

### 4.1 LOAD of R rows, read latency L

| Cycle | Event |
| --- | --- |
| t | `start` |
| t+1 … t+R | request i in cycle t+1+i (one per cycle, never stalled) |
| t+1+L … t+R+L | response i written to buffer row buf_addr+i in cycle t+1+i+L |
| t+R+L | `done`; `busy` = 0 from t+R+L+1 |

R = 0: `done` in t+1.

### 4.2 STORE of R rows

| Cycle | Event |
| --- | --- |
| t | `start` |
| t+1 | source read of row 0 (`src_re`) |
| t+2+4i … t+5+4i | beats 0…3 of row i; row i+1 read in t+5+4i |
| t+4R+1 | last beat accepted, `done`; `busy` = 0 from t+4R+2 |

R = 0: `done` in t+1. With write stalls, each stall cycle delays everything
after it by one cycle.

## 5. Reset

Reset: FSM state, `row_valid_q`, `start_dropped`. Not reset: descriptor and
address/count registers (written on accept), the beat index (written on
accept).

## 6. Tests (`tb/dma/`, top `sa_dma_top` = DMA + weight/input buffers + a
STORE source `sa_sram`; the buffers' read ports and the source's write port
are exposed)

1. LOAD random shapes (rows 1 … IN_DEPTH, random strides, both targets),
   contents checked by reading the buffers back; always-ready memory: the
   `done` cycle equals §4.1 for L ∈ {1, 3}.
2. STORE random rows from the source; memory contents checked; always-ready
   memory: `done` cycle equals §4.2.
3. Both with random stalls on every channel (req, resp, write) and
   max_outstanding ∈ {1, 4}: contents correct.
4. A protocol checker on every cycle: a raised `rd_req_valid`/`wr_req_valid`
   stays raised with identical payload until accepted; no request outside a
   running command; buffer writes only for responses.
5. `rows = 0`, `start` while busy (ignored, `start_dropped`).
