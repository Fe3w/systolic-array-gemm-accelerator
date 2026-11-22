# results/

Measured data only. Every file here must be produced by a committed script, and
docs/README/PRs must cite the file a number came from. Predictions never go here
unless the file name says `predicted`.

Planned layout:

- `latency/`       measured fill/drain and per-tile cycles (M4)
- `synth/`         Yosys/nextpnr reports and summary JSON (M7)
- `verification/`  random-campaign summaries: count, seeds, failures (M10)
- `perf/`          cycles and utilization per GEMM shape and tile order (M11)
- `scalesim/`      SCALE-Sim configs, inputs and outputs (M11)
- `asic/`          LibreLane SKY130 summaries (M12)

CSV schemas are defined in `docs/BRIEF.md` section 9.
