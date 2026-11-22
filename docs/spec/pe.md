# Spec: processing element `sa_pe`

Status: written in M1 before the RTL; implemented and verified in M2
(`rtl/pe/sa_pe.sv`, `tb/pe/`). **M7b (D-022) split the MAC into two stages**
(multiply, then add) to cut the critical path measured in M7
(`results/synth/sa_array_S8_0c93383.json`); ports are unchanged, the partial
sum path now takes 2 cycles. Any change must update this file and the tests first.

## 1. Function

One weight-stationary MAC cell (BRIEF §5.1, §6.1). Each cycle (M7b):

```
p_q        <= a_valid_in ? a_in * w_q : 0      stage 1: multiply (16-bit product)
psum_out_q <= psum_in + sext32(p_q)            stage 2: add, one cycle later
a_out_q    <= a_in
a_valid_q  <= a_valid_in            (cleared by rst)
w_q        <= w_load ? w_in : w_q   (weight shift chain during LOAD_W)
```

So the activation that arrives in cycle t is added to the `psum_in` presented
in cycle **t + 1**, and the sum is visible on `psum_out` in cycle t + 2.

* `a_in * w_q` is an 8×8 signed multiply giving a 16-bit signed product
  (range −16256 … 16384), sign-extended to 32 bits before the add.
* The add is a 32-bit two's-complement add that wraps on overflow (D-004a,
  decided, matching `golden.gemm(semantics="wrap")`).
* An invalid activation contributes zero, so the PE passes `psum_in` through
  unchanged. This costs one AND gate per product bit and makes bubbles in the
  activation stream harmless.

## 2. Ports

| Port | Dir | Width | Registered? | Meaning |
| --- | --- | --- | --- | --- |
| `clk` | in | 1 | — | clock, all flops on the rising edge |
| `rst` | in | 1 | — | synchronous, active-high (D-005) |
| `w_load` | in | 1 | — | capture `w_in` into `w_q` at this edge |
| `w_in` | in | 8 signed | — | weight from the PE above (or the weight buffer for row 0) |
| `w_out` | out | 8 signed | yes (`w_q`) | stored weight, feeds `w_in` of the PE below |
| `a_in` | in | 8 signed | — | activation from the left |
| `a_valid_in` | in | 1 | — | `a_in` is valid |
| `a_out` | out | 8 signed | yes | `a_in` delayed one cycle, to the right |
| `a_valid_out` | out | 1 | yes | `a_valid_in` delayed one cycle |
| `psum_in` | in | 32 signed | — | partial sum from above (0 for row 0) |
| `psum_out` | out | 32 signed | yes | `psum_in + a·w` (or `psum_in` if invalid) |

Parameters: `DATA_W = 8`, `ACC_W = 32`. They exist to make widths explicit;
only the default values are tested in the MVP.

There is no separate `psum_valid`: in the skewed array, `psum_out` of PE(r, c)
is meaningful exactly when `a_valid_out` of the same PE is high (same edge, same
activation). The bottom row's `a_valid_out` is the column's output valid.

## 3. Weight loading (D-012, decided for M2)

`w_q` is both the stationary weight and one stage of a per-column shift chain
(`w_out = w_q`). `w_load` is broadcast to every PE. Loading a column of S PEs
takes **S cycles** with `w_load = 1`, feeding the bottom row's weight first.
The array must not compute while `w_load = 1` (no double buffering in the MVP).
M3 decides whether this stays or becomes row-parallel loading (BRIEF §6.2).

Cycle table for a 3-PE column (PE0 at the top). "Cycle n" is the interval after
rising edge n; values shown are register contents during that cycle.

| Cycle | `w_load` | PE0 `w_in` | PE0 `w_q` | PE1 `w_q` | PE2 `w_q` |
| --- | --- | --- | --- | --- | --- |
| 0 | 1 | W2 | – | – | – |
| 1 | 1 | W1 | W2 | – | – |
| 2 | 1 | W0 | W1 | W2 | – |
| 3 | 0 | x | **W0** | **W1** | **W2** |
| 4+ | 0 | x | W0 | W1 | W2 (held) |

Weight load latency L_w = S cycles (S = 3 here), predicted (analytical).

## 4. Cycle tables

### 4.1 3-PE row (activation path, weights W0 W1 W2 already loaded)

Activation `a` is driven into PE0 during cycle 0.

| Cycle | PE0 `a_in` | PE0 `a_out` = PE1 `a_in` | PE1 `a_out` = PE2 `a_in` | PE2 `a_out` |
| --- | --- | --- | --- | --- |
| 0 | a | – | – | – |
| 1 | – | a | – | – |
| 2 | – | – | a | – |
| 3 | – | – | – | a |

One cycle per hop. `a_valid` moves with `a` exactly.

### 4.2 3-PE column (partial-sum path, two-stage MAC since M7b)

Row r receives its activation `a_r` in cycle r (the input skew of BRIEF §5.2,
unchanged). PE0 `psum_in = 0`. `p` = the stage-1 product register.

| Cycle | PE0 | PE1 | PE2 |
| --- | --- | --- | --- |
| 0 | a0 in | – | – |
| 1 | p = a0·W0; add 0 + p | a1 in | – |
| 2 | `psum_out` = a0·W0 | p = a1·W1; add a0·W0 + p | a2 in |
| 3 | – | `psum_out` = a0·W0 + a1·W1 | p = a2·W2; add (PE1 sum) + p |
| 4 | – | – | `psum_out` = **a0·W0 + a1·W1 + a2·W2** |

PE(r−1)'s sum is visible in cycle r + 1, exactly when PE(r)'s add stage
needs it (its activation arrived in cycle r). So the skew of one cycle per row
still lines everything up, and the column only gains one cycle in total:
fill latency S + 1 cycles from row 0's input to the column output (was S).
Steady state unchanged: one activation row per cycle.

Predicted (analytical) PE latency: `a_out`, `a_valid_out` 1 cycle after their
inputs; `psum_out` 2 cycles after `a_in`/`a_valid_in` and 1 cycle after
`psum_in`.

## 5. Reset behaviour (D-005)

| Register | Reset? | Why |
| --- | --- | --- |
| `a_valid_q` | yes, to 0 | control: invalid data must never look valid |
| `a_out_q` | no | datapath, gated by `a_valid` |
| `psum_out_q` | no | datapath, gated by the bottom row's `a_valid` |
| `w_q` | no | written by LOAD_W before any COMPUTE; COMPUTE before LOAD_W is a controller error (BRIEF §6.5) |

Reset concern to note: with `w_q` unreset, a COMPUTE before any LOAD_W
produces garbage silently at the PE level. The controller (M8) must flag it.

## 6. M2 test list (written as cocotb tests before the RTL)

All tests use `tb.common.utils.get_rng(<test name>)` and print the seed.

1. **Exhaustive products:** load each w in −128…127, sweep a over −128…127 with
   `psum_in = 0`; check `psum_out == a·w` for all 65,536 pairs.
2. **Random accumulate:** random `psum_in` (full int32), random a, w; check
   against `golden.to_int32(psum_in + a·w)`, including forced wrap cases
   (`psum_in = 2³¹ − 1`, a·w > 0 and `psum_in = −2³¹`, a·w < 0).
3. **Corners:** −128 × −128, −128 × 127, 127 × 127, 0 × anything, x × 0.
4. **Weight hold:** load w once, then stream 100 random activations with
   `w_load = 0`; the weight never changes and `w_out` stays equal to it.
5. **Weight shift-through:** with `w_load = 1`, `w_out` equals the `w_in` from
   the previous cycle; with `w_load = 0`, `w_out` holds.
6. **Activation propagation:** `a_out`, `a_valid_out` equal the inputs one
   cycle earlier, for a random valid pattern.
7. **Invalid activation passes psum through:** `a_valid_in = 0` with a non-zero
   `a_in` gives `psum_out == psum_in`.
8. **Reset:** `a_valid_out == 0` after reset even if `a_valid_in` was 1 during
   reset; a one-cycle reset mid-stream clears it.
9. **3-PE chain (row and column)** built in the testbench from three PE
   instances is out of scope for M2; it is covered by the 4×4 array tests in
   M3. M2 checks single-PE latency only.

## 7. Shared pipeline register `sa_reg`

`rtl/common/sa_reg.sv` (M1): W-bit data plus valid, D stages, `D = 0` is a
wire, valid bits reset, data not reset. Tested in `tb/reg/`. Intended for the
input skew lines (row r: D = r) and output de-skew lines (column c:
D = S − 1 − c) in M3. The PE keeps its own registers so its single-cycle
behaviour is visible in one file.

## 8. Implementation notes (M2)

* Operands are sign-extended explicitly to `PROD_W = 2·DATA_W` bits and
  multiplied as `signed`; the product is sign-extended explicitly to `ACC_W`.
  Nothing relies on SystemVerilog's implicit width/sign rules. Requires
  `ACC_W > 2·DATA_W` (32 > 16 by default).
* Observation only (no numbers; M7 owns synthesis results): Yosys
  `synth_ecp5 -top sa_pe` maps the multiply to one `MULT18X18D`.
* The exhaustive test drives 256 weights × (1 load cycle + 256 MACs + 1 flush
  cycle) = 66,048 cycles (from the test's structure; the M2 plan predicted
  65,792 because it left out the flush cycle that checks the last MAC).
