# SysArray vs SCALE-Sim v3 (S = 8, weight stationary)

Inputs: `results/scalesim/sysarray_s8_ws.cfg`, `topology.csv`, `layout.csv`
(written by `scripts/scalesim/run_scalesim.py --shapes sq8,sq16,sq64,odd`).
SCALE-Sim output: `results/scalesim/COMPUTE_REPORT.csv`. SysArray numbers:
`results/perf/f5c0a0c.csv` (RTL cycle counters, order A, m_c = min(M, 256)).

| Shape | SysArray cycles (RTL) | SysArray util. | SCALE-Sim total cycles (incl. prefetch) | SCALE-Sim stall cycles | SCALE-Sim overall util. |
| --- | --- | --- | --- | --- | --- |
| sq8 (8×8×8) | 103 | 0.078 | 43 | 0 | 27.6 % |
| sq16 (16×16×16) | 438 | 0.146 | 240 | 0 | 42.4 % |
| sq64 (64×64×64) | 12,696 | 0.323 | 14,078 | 7,960 | 30.4 % |
| odd (100×37×53) | 10,355 | 0.296 | 4,570 | 0 | 71.8 % |
| sq256 (256×256×256) | 594,528 | 0.441 | 2,963,801 | 2,678,515 | 8.8 % |

What ran: these four shapes (M11), plus sq256 in M11b from a separate run
(`run_scalesim.py --shapes sq256 --out results/scalesim/sq256`, output
`results/scalesim/sq256/COMPUTE_REPORT.csv`, ~2 h wall clock in a cloud
environment). The other BERT/ResNet shapes have no SCALE-Sim result. SysArray's
sq256 row is order A with m_c = 256 (`results/perf/f5c0a0c.csv` line 5).

Reading the gap:
- SCALE-Sim models SRAMs that prefetch from DRAM while the array computes
  (double buffering) and charges only bandwidth stalls; SysArray's MVP runs
  LOAD_W, LOAD_A, COMPUTE and STORE one after another with command-decode
  cycles in between (`docs/spec/ctrl.md` §3). So for sq8, sq16 and odd SCALE-Sim
  needs fewer cycles: the difference is SysArray's serialized DMA and per-command
  overhead, the same limiter the roofline shows (`results/perf/f5c0a0c_roofline.png`).
- For sq64 SCALE-Sim reports 7,960 stall cycles with this config (8 words/cycle
  interface, 1 KiB filter SRAM — its minimum) and ends slightly above
  SysArray's count. With these settings SCALE-Sim does not get the full benefit
  of its overlap on this shape. For sq256 the effect dominates: 2,678,515 of
  2,963,801 cycles are stalls, because the minimum SRAM sizes chosen to mirror
  SysArray's small buffers force SCALE-Sim to refetch from DRAM at 8 words per
  cycle. The sq256 comparison therefore says more about that config than about
  either array.
- SCALE-Sim's GEMM topology maps M to ifmap rows, N to filters and K to the
  reduction, like SysArray's C = A·B; its "utilization" definitions (overall vs
  compute vs mapping efficiency) differ from SysArray's useful MACs /
  (S² · cycles), so compare cycle counts first.

Conclusion: the comparison supports the analysis in the README: overlapping
DMA with compute (the double-buffering extension) is what separates the MVP
from an ideal prefetching WS array of the same size.

## M11c re-run attempt (14 Nov 2026)

Config: the same `sysarray_s8_ws.cfg`. It already uses SysArray's buffer
sizes from D-016: input 2 KiB (256 rows × 8 B), accumulator 8 KiB
(256 rows × 8 × 4 B), weight 1 KiB (SCALE-Sim's minimum, above SysArray's
64 B weight tile).

| Shape | Command | Outcome |
| --- | --- | --- |
| bert_proj (128×768×768) | `run_scalesim.py --shapes bert_proj` under `timeout 10800` | stopped at the 3-hour limit (exit 124, 10,800 s), no report |
| r50_3x3 (3136×64×576) | `run_scalesim.py --shapes r50_3x3` under `timeout 10800` | stopped at the 3-hour limit (exit 124, 10,800 s), no report |

Not run: bert_ffn_down, bert_ffn_up and r50_1x1 (more MACs than bert_proj,
which already exceeded the limit). The SCALE-Sim comparison therefore covers
sq8, sq16, sq64, odd and sq256 only. For sq256 most SCALE-Sim cycles are
stalls from its DRAM-bandwidth model with these small SRAMs, so the large-shape
comparison measures SCALE-Sim's memory model more than the dataflow. The
measured RTL numbers for all ten shapes are in `results/perf/`.
