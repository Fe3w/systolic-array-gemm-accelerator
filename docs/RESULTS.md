# Results index (provenance)

Every file in `results/` is produced by a committed script, at the commit named
in the file name. The table lists that commit, the script and the milestone
that produced it (D-018). These commits belong to the development repository;
the published copy of this repository starts a fresh history, so they are not
in its `git log`
(D-034). To reproduce a result, run the script on the current code: the
numbers in the README come with the command that regenerates them.
`compiler/tests/test_results_provenance.py` checks that every commit named in
`results/` is listed below (and, in the development repository, that it
exists).

| Files | Producing commit | Script | Milestone |
| --- | --- | --- | --- |
| `results/latency/latency_44b58e7.csv` | 44b58e7 | `scripts/measure/latency.py` | M4 |
| `results/synth/*_0c93383.json` | 0c93383 | `scripts/synth/ecp5.py` | M7 |
| `results/synth/sa_core_S8_488229c.json` | 488229c | `scripts/synth/ecp5.py` | M7B |
| `results/synth/*_d4aedec*.json`, `results/latency/latency_d4aedec.csv` | d4aedec | `scripts/synth/ecp5.py`, `scripts/measure/latency.py` | M7B |
| `results/verification/campaign_3dbf80b.json` | 3dbf80b | `scripts/verify/campaign.py` | M10 |
| `results/perf/f5c0a0c*` | f5c0a0c | `scripts/measure/perf.py`, `scripts/measure/plot_perf.py` | M11 |
| `results/scalesim/COMPUTE_REPORT.csv`, `COMPARISON.md` | 6807d80 (script) | `scripts/scalesim/run_scalesim.py` | M11 |
| `results/synth/sa_core_S8_b54dd8b.json`, `sa_top_S8_b54dd8b.json` | b54dd8b | `scripts/synth/ecp5.py` | M11B |
| `results/synth/sa_top_S8_433f87e.json` | 433f87e | `scripts/synth/ecp5.py` | M11B |
| `results/synth/sa_top_S8_7d6f36a.json` | 7d6f36a | `scripts/synth/ecp5.py` | M11B |
| `results/synth/*_c64045a*.json` | c64045a | `scripts/synth/ecp5.py` | M11B |
| `results/scalesim/sq256/*` | 9c2f20a (script) | `scripts/scalesim/run_scalesim.py --shapes sq256 --out results/scalesim/sq256` | M11B |
| `results/synth/sa_core_S8_931741d.json`, `sa_top_S8_931741d.json` | 931741d | `scripts/synth/ecp5.py` | M13 |
| `results/synth/sa_top_S8_297a337.json` | 297a337 | `scripts/synth/ecp5.py` | M13 |
| `results/synth/sa_top_S8_ea8fa1b.json` | ea8fa1b | `scripts/synth/ecp5.py` | M13 |
| `results/perf/931741d*` | 931741d | `scripts/measure/perf.py`, `scripts/measure/plot_perf.py` | M13 |
| `results/verification/campaign_126930e.json` | 126930e | `scripts/verify/campaign.py` | M13 |
| `results/synth/sa_top_S8_dc61168.json`, `sa_top_S8_ebfc542.json` | dc61168, ebfc542 | `scripts/synth/ecp5.py` | M11C |
| `results/verification/campaign_cd2849e.json` | cd2849e | `scripts/verify/campaign.py` | M11C |
| `results/perf/be6f466*` | be6f466 | `scripts/measure/perf.py`, `scripts/measure/plot_perf.py` | M11C |
| `results/asic/sa_array_S8_f1981ab_20ns.json` (+ `raw/`) | f1981ab | `scripts/librelane/run.py` | M12 |
| `results/asic/sa_array_S8_a310e13_15ns.json` (+ `raw/`; summary written later with `--resummarize`) | a310e13 | `scripts/librelane/run.py` | M12 |
| `results/asic/sa_array_S8_cc4aee5_15ns_hold0p25.json` (+ `raw/`) | cc4aee5 | `scripts/librelane/run.py` | M12 |
| `results/asic/sa_array_S8_0d8ca14_15ns_io30.json` (+ `raw/`) | 0d8ca14 | `scripts/librelane/run.py` | M12 |
| `results/asic/sa_array_S4_bb277bc_15ns_io30.json` (+ `raw/`) | bb277bc | `scripts/librelane/run.py` | M12 |
| `results/asic/sa_array_S8_c553cf7_15ns_io30_nodly_grtfix.json` (+ `raw/`) | c553cf7 | `scripts/librelane/run.py` | M12B |
| `results/asic/sa_array_S8_c946b2e_15ns_io30_nox1_margin.json` (+ `raw/`) | c946b2e | `scripts/librelane/run.py` | M12B |
| `results/asic/sa_array_S8_bbe0222_15ns_io30_nox1_margin_grttiming.json` (+ `raw/`) | bbe0222 | `scripts/librelane/run.py` | M12B |
