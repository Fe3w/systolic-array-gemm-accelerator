# compiler/

Python package `sysarray` (created in M1):

- `golden.py`: reference int8 x int8 -> int32 GEMM with the chosen overflow semantics
- `tiler.py`: splits M x N x K into array tiles, tile orders A and B (M9)
- `commands.py`: command-stream encoding shared with the testbench (M8/M9)
- `predict.py`: analytical cycle/utilization/traffic predictor (M9)

Unit tests live in `compiler/tests/` and run with `make test-py`.
