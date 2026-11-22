# tb/

cocotb 2.x testbenches, run on Verilator through pytest.

- `tb/common/` shared helpers: `runner.py` (build + run with `cocotb_tools.runner`,
  waves via `SYSARRAY_WAVES=1`, seeds via `SYSARRAY_SEED`) and `utils.py`.
  Created in M1.
- `tb/<block>/cocotb_<block>.py`: the cocotb tests.
- `tb/<block>/test_<block>.py`: the pytest launcher that calls the shared runner.

Every random test prints its seed. Replay a failure with `SYSARRAY_SEED=<seed> make test-rtl`.
