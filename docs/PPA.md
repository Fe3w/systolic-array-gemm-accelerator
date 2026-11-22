# Hardware cost: FPGA and ASIC (PPA)

What the design costs in real silicon: Fmax and resources on a Lattice ECP5
FPGA, and area and timing on SkyWater SKY130 after place-and-route. Every
number comes from a file in `results/` (cited next to it). Back to the
[README](../README.md).

**Summary.** The full accelerator (`sa_top`, S = 8) runs at 92.89 MHz on an
ECP5 LFE5U-85F using 64 MULT18X18D DSPs, one per PE
(`results/synth/sa_top_S8_ebfc542.json`). The 8 × 8 array (`sa_array`) places
and routes on SKY130 at 15 ns in a 1.053 mm² core with DRC, LVS and antenna
checks at 0; it is not yet fully signed off, because every run still reports
max-slew violations (`results/asic/sa_array_S8_0d8ca14_15ns_io30.json`;
details and the next step below).

## FPGA cost (Yosys + nextpnr-ecp5, LFE5U-85F, speed grade 6)

| Top | Fmax (MHz) | MULT18X18D | FF | LUT4 | CCU2C | DP16KD | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sa_pe` | 191.13 | 1 | 49 | 1 | 16 | 0 | `results/synth/sa_pe_S0_c64045a.json` |
| `sa_array` S = 8 | 112.99 | 64 | 3,896 | 15 | 784 | 0 | `results/synth/sa_array_S8_c64045a.json` |
| `sa_core` S = 8 (double buffering) | 98.93 | 64 | 5,818 | 986 | 973 | 10 | `results/synth/sa_core_S8_931741d.json` |
| `sa_top` S = 8 (final) | 92.89 | 64 | 7,301 | 2,728 | 4,774 | 10 | `results/synth/sa_top_S8_ebfc542.json` |

Fmax of `sa_core` went from 60.55 MHz (`results/synth/sa_core_S8_0c93383.json`)
to 82.4–85.2 MHz after a timing pass (`results/synth/sa_core_S8_d4aedec*.json`,
buffer → array register, two-stage MAC) and to the numbers above after a
second one (3-stage accumulator read-modify-write; the PE's product register
mapped onto the MULT18X18D output register, D-027). Double buffering's
concurrent dispatcher first cost
`sa_top` 84.63 → 71.07 MHz (`results/synth/sa_top_S8_931741d.json`: 48-bit
gate compares in the dispatch path); small gate down-counters and a delayed
`macs_issued` update brought it back to 84.18 MHz (D-031,
`results/synth/sa_top_S8_ea8fa1b.json`). A second CHECK cycle (D-028) and the command's row-range ends registered at accept give 92.89 MHz, at a
cost of one cycle per command (utilization −0.001 to −0.009,
`results/perf/be6f466.csv` vs `931741d.csv`). Remaining limiter in `sa_core`:
the accumulator BRAM → STORE data output. Most of `sa_top`'s CCU2C are the six
48-bit performance counters and the DMA address arithmetic.

## ASIC (SkyWater SKY130, LibreLane)

`sa_array` at S = 8 placed and routed with LibreLane 3.0.17 on `sky130A`
(`sky130_fd_sc_hd`), timing analysed at nine corners (`make asic`,
`scripts/librelane/`, D-032). Every run is listed, including the failed ones:

| Run | Clock period | I/O constraint | Outcome | Worst setup slack | Worst hold slack | Max-slew violations | File |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 20 ns | 20 % (default) | timing met; slew violations | +5.351 ns | +0.090 ns | 12,787 | `results/asic/sa_array_S8_f1981ab_20ns.json` |
| 2 | 15 ns | 20 % | hold fails at ss corners (input ports only) | +0.401 ns | −0.198 ns | 12,827 | `results/asic/sa_array_S8_a310e13_15ns.json` |
| 3 | 15 ns | 20 %, hold margin 0.25 ns | setup and hold fail | −0.540 ns | −0.175 ns | 12,711 | `results/asic/sa_array_S8_cc4aee5_15ns_hold0p25.json` |
| 4 | 15 ns | 30 % | timing met; slew violations | +0.351 ns | +0.090 ns | 12,787 | `results/asic/sa_array_S8_0d8ca14_15ns_io30.json` |
| 6 | 15 ns | 30 %, no `clkdlybuf4s*` cells, post-route repair on | slew worse (repair used x1 buffers) | +0.614 ns | +0.092 ns | 14,831 | `results/asic/sa_array_S8_c553cf7_15ns_io30_nodly_grtfix.json` |
| 7 | 15 ns | 30 %, also no x1 buffers, repair margins 40/30 % | slew mostly repaired, setup fails at ss | −0.764 ns | +0.041 ns | 113 | `results/asic/sa_array_S8_c946b2e_15ns_io30_nox1_margin.json` |
| 8 | 15 ns | as 7, post-route margin 40 %, post-route setup repair | **best slew run**; setup fails at ss (7 endpoints) | −0.453 ns | +0.059 ns | 91 | `results/asic/sa_array_S8_bbe0222_15ns_io30_nox1_margin_grttiming.json` |

Run 2's hold failures are all input-port → first-flop paths at the slow
corner: the default input delay (3.0 ns, 20 % of 15 ns) is smaller than the
clock tree's insertion delay there (≈ 3.4 ns,
`results/asic/raw/sa_array_S8_a310e13_15ns/sta_summary.rpt`); every
register-to-register hold path passes. Raising the hold-repair margin (run 3)
only added buffers on real paths. Run 4 assumes the inputs arrive 4.5 ns after
the clock edge instead (an assumption about the surrounding chip). DRC (Magic, KLayout), LVS and antenna checks report 0 in
every run, but every run also has max-slew violations that LibreLane reports
as warnings (column above), so no run counts as a clean sign-off.

**Slew repair.** In run 4, 12,706 of the 12,771 violating pins at the
slow corner are driven by `clkdlybuf4s25_1`, a weak clock-delay buffer the
placement repair used as a fanout buffer (fanout ≈ 10); the signals behind
them are the PE weight and activation registers, the skew registers and
`w_load` (`scripts/librelane/slew_diag.py`). Excluding the delay cells (run 6)
only moved the problem to `clkbuf_1`/`buf_1`; also excluding the x1 buffers
and widening the repair margins (runs 7, 8) cut the violations to 113 and 91,
but the extra buffering now fails setup at the slow corners. LibreLane's
timing repair optimises for its place-and-route corner (`PNR_CORNERS`,
default `nom_tt`, where run 8 has +5.006 ns), not for the slow corner where
sign-off fails; making it target the slow corner is the recommended next step
(D-033). Run 8's remaining 91 violations are on 13 nets (internal multiplier
nets driven by `clkbuf_2`, `u_pe.psum_d` driven by `xnor2_4`, `av_q`, `w_load`,
`clk`), all at ss and tt corners.

`sa_array` (S = 8) on both targets:

| | ECP5 LFE5U-85F (nextpnr) | SKY130 `sky130_fd_sc_hd` (LibreLane, run 4; run 8 in brackets) |
| --- | --- | --- |
| Clock | Fmax 112.99 MHz | 15 ns (66.7 MHz): setup/hold met at all corners with 12,787 max-slew violations [91 violations, setup −0.453 ns at ss]; slack-derived 68.27 MHz slow corner (ss, 100 °C, 1.60 V), 113.42 MHz typical (tt, 25 °C, 1.80 V) |
| Multipliers | 64 MULT18X18D | standard cells |
| Registers | 3,896 FFs (plus the product registers inside the 64 DSPs, D-027) | 4,832 flip-flops (product registers included) |
| Logic | 15 LUT4, 784 CCU2C | 31,804 combinational cells, 58,693 standard cells in total incl. buffers |
| Area | – | core 1.053 mm², standard cells 0.509 mm² [0.502 mm², 59,041 cells] (die 1.089 mm², 40 % target utilization) |
| Source | `results/synth/sa_array_S8_c64045a.json` | `results/asic/sa_array_S8_0d8ca14_15ns_io30.json` |

Scaling point (same 15 ns / 30 % settings; timing met, 3,207 max-slew violations): S = 4 has
13,358 standard cells, 0.116 mm² of standard-cell area and +0.995 ns worst
setup slack (`results/asic/sa_array_S4_bb277bc_15ns_io30.json`). From S = 4 to
S = 8 (4× the PEs) the standard-cell area grows 4.38×; the worst-corner
slack-derived clock moves from 71.40 to 68.27 MHz.

Slack-derived frequency = 1000 / (period − worst setup slack), assuming the
paths and the I/O budget scale with the period; only 15 ns and 20 ns were
run. At the slow corner the worst setup path is register-to-register
in both timing-clean runs; at the typical corner it is an I/O path (run 4:
register-to-register slack 7.659 ns vs 6.183 ns overall,
`results/asic/raw/sa_array_S8_0d8ca14_15ns_io30/sta_summary.rpt`), so the
typical-corner figure is set by the assumed I/O budget, not by the array.

## Reproduce

```bash
make synth              # Yosys + nextpnr-ecp5 for every top, ~5–10 min per top -> results/synth/
make asic PERIOD=15     # LibreLane SKY130 place-and-route of sa_array in Docker, ~60 min -> results/asic/
```

The LibreLane setup and every run option: `scripts/librelane/README.md`.
Decisions behind the flow: D-027 (DSP mapping), D-028 and D-031 (controller
timing), D-032 (SKY130 flow), D-033 (slew repair) in
[DECISIONS.md](DECISIONS.md).
