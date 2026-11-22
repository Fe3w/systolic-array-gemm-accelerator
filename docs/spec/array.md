# Spec: PE grid `sa_grid` and skewed array `sa_array`

Status: written in M3 before the RTL. Decisions: D-012 (weight shift chain),
D-014 (grid + wrapper, packed ports), D-015 (reload after drain).
Numbers were first derived as predictions from the PE cycle table
(`docs/spec/pe.md` §4). M3's tests assert them at S = 2, 3, 4 and M4 measured
them at S = 4, 8: `results/latency/latency_44b58e7.csv` (from
`scripts/measure/latency.py`) matches latency = 2S − 1 and
T_tile = M + 3S − 1 in every row (§7). **M7b (D-022) pipelined the PE MAC**
(`docs/spec/pe.md` §4.2): latency is now **2S** and T_tile **M + 3S**
(§4 below; re-measured in M7b); the reload rule (§3 rule 3) is unchanged.

## 1. Structure

```
            w_row[0..S-1] (north edge, all columns in parallel, during w_load)
                 │      │      │      │
 a_row[0] ─D=0──►PE00──►PE01──►PE02──►PE03──► (unused)
 a_row[1] ─D=1──►PE10──►PE11──►PE12──►PE13──►
 a_row[2] ─D=2──►PE20──►PE21──►PE22──►PE23──►
 a_row[3] ─D=3──►PE30──►PE31──►PE32──►PE33──►
                 │      │      │      │
               D=3    D=2    D=1    D=0      output de-skew (sa_reg)
                 ▼      ▼      ▼      ▼
              c_row[0] c_row[1] c_row[2] c_row[3]     (S = 4 shown)
```

* `sa_grid` = the S×S PEs only. PE(r, c) gets `a` from PE(r, c−1) (or the
  west edge), `psum` and `w` from PE(r−1, c) (or 0 / the north edge).
* `sa_array` = `sa_grid` + input skew (`sa_reg` with D = r on row r) +
  output de-skew (`sa_reg` with D = S − 1 − c on column c).
* Mapping (BRIEF §5.1): PE(r, c) holds W[r][c] = B[k0 + r][n0 + c]. Row m of the
  activation strip, A[m][k0 .. k0+S−1], enters as one `a_row` vector; output
  `c_row[c]` = Σ_r A[m][k0+r] · W[r][c].

## 2. Ports

Vector ports are packed `[S-1:0][W-1:0]`: element i occupies bits
`[i*W +: W]` (element 0 in the low bits). Each element is a two's-complement
value; the testbench packs and unpacks with `tb.common.utils.pack/unpack`.

### `sa_grid #(S, DATA_W = 8, ACC_W = 32)`

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk`, `rst` | in | 1 | clock; synchronous active-high reset (D-005a) |
| `w_load` | in | 1 | broadcast to every PE |
| `w_in` | in | S × DATA_W | weight entering the top of each column |
| `a_in` | in | S × DATA_W | activation entering each row (already skewed) |
| `a_valid_in` | in | S | valid per row (already skewed) |
| `psum_out` | out | S × ACC_W | bottom-row `psum_out` of each column |
| `valid_out` | out | S | bottom-row `a_valid_out` of each column (qualifies `psum_out[c]`) |

### `sa_array #(S, DATA_W = 8, ACC_W = 32)`

| Port | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `clk`, `rst` | in | 1 | as above |
| `w_load` | in | 1 | shift `w_row` into the top row this cycle |
| `w_row` | in | S × DATA_W | one row of the weight tile per load cycle |
| `a_valid` | in | 1 | `a_row` holds a valid activation row |
| `a_row` | in | S × DATA_W | A[m][k0 .. k0+S−1], all S elements in the same cycle |
| `c_valid` | out | 1 | `c_row` holds a finished output row |
| `c_row` | out | S × ACC_W | C contribution of this K-slice for one row, all columns aligned |

## 3. Usage rules

1. **Weight load (D-012):** assert `w_load` for exactly S cycles, presenting
   B[k0+S−1] first and B[k0] last. After the last load edge PE(r, c) holds
   W[r][c].
2. **No compute during load:** `a_valid = 0` in every `w_load` cycle and until
   the first activation can use the final weights (the cycle after the last
   `w_load`).
3. **Reload after drain (D-015):** the first `w_load` of the next tile may be
   asserted no earlier than the cycle in which PE(S−1, S−1) performs its last
   MAC for the previous tile, i.e. cycle `t_last + 2S − 2` where `t_last` is
   the cycle the last valid `a_row` was presented. `w_q` changes only at the
   end of a `w_load` cycle, so that last MAC still uses the old weight.
   Asserting `w_load` one cycle earlier corrupts `c_row[S−1]` of the last row.
4. Rows may have bubbles (`a_valid = 0` cycles); outputs appear only for valid
   rows, in order, each exactly 2S cycles after its input (2S − 1 before M7b).

## 4. Cycle tables (S = 4, predicted)

"Cycle t" is the interval after rising edge t. Inputs presented in cycle t are
captured at edge t + 1.

### 4.1 Weight load (cycles 0..3) — `w_q` contents per row of PEs

| Cycle | `w_load` | `w_row` | row 0 | row 1 | row 2 | row 3 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | B[3] | – | – | – | – |
| 1 | 1 | B[2] | B[3] | – | – | – |
| 2 | 1 | B[1] | B[2] | B[3] | – | – |
| 3 | 1 | B[0] | B[1] | B[2] | B[3] | – |
| 4 | 0 | – | **B[0]** | **B[1]** | **B[2]** | **B[3]** |

L_w = S = 4 cycles. First legal `a_valid` cycle: 4.

### 4.2 One row through the array

Row m presented in cycle t0 (all S elements). Input skew delays row r by r,
so A[m][r] reaches PE(r, c) in cycle **t0 + r + c** and is multiplied there;
PE(r, c) adds in cycle t0 + r + c + 1 and its sum is visible in t0 + r + c + 2,
exactly when PE(r+1, c) adds (its activation arrived in t0 + r + 1 + c). The
bottom of column c (`psum_out[c]`, `valid_out[c]`, the valid delayed one extra
cycle in `sa_grid`) shows the finished sum in cycle **t0 + S + c + 1**.
De-skew adds S − 1 − c cycles, so every column shows row m in cycle
**t0 + 2S**. (Before M7b's two-stage MAC: t0 + S + c and t0 + 2S − 1.)

| Cycle (t0 = 4) | PE row 0 multiply | row 1 | row 2 | row 3 | grid `psum_out` valid in column | `c_valid` |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | c0 | – | – | – | – | 0 |
| 5 | c1 | c0 | – | – | – | 0 |
| 6 | c2 | c1 | c0 | – | – | 0 |
| 7 | c3 | c2 | c1 | c0 | – | 0 |
| 8 | – | c3 | c2 | c1 | – | 0 |
| 9 | – | – | c3 | c2 | c0 | 0 |
| 10 | – | – | – | c3 | c1 | 0 |
| 11 | – | – | – | – | c2 | 0 |
| 12 | – | – | – | – | c3 | **1** (row m) |

(Each PE adds one cycle after its multiply.) Latency from `a_row` to `c_row`:
**2S = 8** cycles.

### 4.3 A tile of M = 3 rows (rows presented in cycles 4, 5, 6)

| Phase | Cycles | Notes |
| --- | --- | --- |
| Weight load | 0–3 | L_w = S |
| Fill + stream | 4–6 | one row presented per cycle |
| Outputs | 12, 13, 14 | rows 0, 1, 2; one per cycle (steady state) |
| Last multiply in PE(3, 3) | 6 + 2S − 2 = 12 | earliest next `w_load` (rule 3) |
| Next tile's first row | 12 + S = 16 | earliest, if its load starts at 12 |

T_tile (first `w_load` to the cycle after the last output) = M + 3S =
15 cycles here (cycles 0..14). Back to back, the next tile starts loading in
cycle 12, three cycles before this tile's last output appears, so the effective
period per tile is still M + 3S − 3 when tiles are chained at the earliest
reload (the reload rule depends on the multiply stage, which did not move).

## 5. Reset (D-005a)

| Register | Reset? |
| --- | --- |
| PE `a_valid_q` (all S²) | yes |
| Input skew valid bits (`sa_reg` rows 1..S−1) | yes |
| Output de-skew valid bits (`sa_reg` columns 0..S−2) | yes |
| PE `w_q`, `a_q`, `psum_q`; skew and de-skew data | no |

After reset no `c_valid` appears until a valid row has been presented and
2S cycles have passed. A reset in the middle of a stream drops every row
in flight (no `c_valid` for them) and keeps the weights.

`c_valid` is the de-skewed valid of column 0. The de-skewed valids of the other
columns are identical by construction (same row, same cycle) and are left
unused; the tests check every column's data, so a misaligned column fails.

## 6. Test list

`tb/grid/` (hand-skewed stimulus, S = 4):
1. Impulse: one row, each PE weight distinct; check `psum_out[c]` and
   `valid_out[c]` appear exactly in cycle t0 + S + c + 1 and nowhere else.
2. Random tile, M = 8, against `golden.gemm`.

`tb/array/` (S = 4, plus S = 2, 3 for test 3):
1. Directed: identity weights, single non-zero weight, all −128 × −128,
   all 127 × 127, mixed signs.
2. Exact latency: one row → `c_valid` exactly 2S cycles later, once.
3. Random tiles, M ∈ {1, 4, 7, 16}.
4. Bubbles: random `a_valid = 0` cycles; outputs in order, one per valid row,
   each 2S cycles after its input.
5. Two tiles back to back with the second load starting at the earliest legal
   cycle (rule 3); both tiles match golden.
6. Reload one cycle too early corrupts the previous tile's last row in column
   S − 1 (documents rule 3; the test asserts the mismatch).
7. Reset mid-stream: rows in flight never produce `c_valid`; a new tile after
   reset (weights reloaded) is correct.

## 7. Measured (M4)

`make measure-latency` → `results/latency/latency_44b58e7.csv` (seed 2026).
One tile from an idle array; outputs checked against golden while measuring.

| S | M | latency_first | t_tile | model 2S − 1 / M + 3S − 1 |
| --- | --- | --- | --- | --- |
| 4 | 1, 2, 8, 13, 64 | 7 | 12, 13, 19, 24, 75 | equal in every row |
| 8 | 1, 2, 8, 13, 64 | 15 | 24, 25, 31, 36, 87 | equal in every row |

Array-only tile utilization M / T_tile at S = 8, computed from that file:
1/24 ≈ 0.042, 8/31 ≈ 0.26, 64/87 ≈ 0.74. Back-to-back tiles chained at the
earliest reload (§3 rule 3): period M + 3S − 3, **predicted (analytical)**
(load S + rows M + wait 2S − 3 until the reload); the timing is exercised by
`tb/array` test_back_to_back_earliest_reload but not yet measured into
`results/`.

### 7.1 Measured after M7b (two-stage MAC)

`make measure-latency` on d4aedec → `results/latency/latency_d4aedec.csv`
(seed 2026): latency_first = 2S (8 at S = 4, 16 at S = 8) and t_tile = M + 3S
(S = 8: 25, 26, 32, 37, 88 for M = 1, 2, 8, 13, 64); `match = True` in all 10
rows.
