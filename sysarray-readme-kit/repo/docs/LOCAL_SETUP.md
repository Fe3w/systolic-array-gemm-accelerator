# Local setup (Ubuntu 24.04)

How to install, verify and reproduce SysArray on a fresh Ubuntu 24.04 laptop.
Every step without `sudo` was run on a fresh clone (4 cores, option B tools)
and works as written; the times below are from that run and depend on the
machine.

The folder used below (any path works):

```bash
export SYSARRAY="$HOME/sysarray"
```

## 1. System packages (needs sudo)

```bash
sudo apt update
```
```bash
sudo apt install -y git make curl build-essential python3-venv python3-pip python3-dev gtkwave
```

- `build-essential` gives `g++` and `make`: Verilator compiles every
  testbench to C++.
- `python3-dev` gives `libpython3.12`, which cocotb loads into the simulator.
- `gtkwave` is only needed for `make demo-waves`.
- **Do not `apt install verilator`.** Ubuntu 24.04 ships Verilator 5.020;
  cocotb 2.x needs ≥ 5.036. Because the tools of step 5 are *appended* to
  `PATH`, an apt Verilator in `/usr/bin` always wins and every RTL test
  fails. If it was installed earlier, remove it:

  ```bash
  sudo apt remove -y verilator
  ```

## 2. Clone (or update)

```bash
mkdir -p "$(dirname "$SYSARRAY")"
if [ -d "$SYSARRAY/.git" ]; then git -C "$SYSARRAY" pull --ff-only; else git clone https://github.com/Fe3w/systolic-array-gemm-accelerator.git "$SYSARRAY"; fi
cd "$SYSARRAY"
```

## 3. Git identity (only if you will commit)

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

## 4. Python virtual environment

```bash
make venv
source .venv/bin/activate
```

`make venv` creates `.venv/` and installs `requirements.txt` (cocotb, NumPy,
pytest, matplotlib). Keep it activated for every step below.

## 5. EDA tools: Verilator ≥ 5.036, Yosys, nextpnr-ecp5

Pick one option.

**Option A: OSS CAD Suite** (prebuilt Verilator, Yosys, nextpnr, GTKWave).
Download the latest `oss-cad-suite-linux-x64-*.tgz` from
https://github.com/YosysHQ/oss-cad-suite-build/releases and unpack it to
`~/tools/oss-cad-suite`. Then **append** its `bin/` to `PATH`:

```bash
export PATH="$PATH:$HOME/tools/oss-cad-suite/bin"
```

Do **not** `source ~/tools/oss-cad-suite/environment`: it puts the suite's
own `python3` first on `PATH`, so cocotb and the tests run outside your venv
and fail to import. With option A, `make synth` uses the suite's native
`nextpnr-ecp5`.

Use one option only. If you tried option B before, leave `~/.local/eda/bin`
off `PATH` (or delete `~/.local/eda`), so all tools come from one place.

**Option B: the repo's installer** (conda-forge, the same tools CI and the
cloud sessions use). Run it **with the venv active**, so the PyPI package
`yowasp-nextpnr-ecp5` is installed into the venv:

```bash
EDA_PREFIX="$HOME/.local/eda" bash scripts/install_eda.sh
export PATH="$PATH:$HOME/.local/eda/bin"
```

This takes a few minutes the first time (about 1 GB). Append, don't prepend:
the conda environment contains its own `python3`, which must stay behind the
venv's.

Check which tools the shell now finds; each should point into the option
you chose (for option A: `~/tools/oss-cad-suite/bin/...`), with nothing from
`/usr/bin` listed first for `verilator`:

```bash
hash -r
type -a verilator yosys nextpnr-ecp5 python3
```

`python3` must be the venv's (`.../sysarray/.venv/bin/python3`).

## 6. Verify

```bash
make check
make lint
make test
make test-repro
```

| Command | Expect | Time |
| --- | --- | --- |
| `make check` | `check_env: OK` (Verilator ≥ 5.036, cocotb 2.x) | seconds |
| `make lint` | `lint: 13 module(s), 0 warnings` | seconds |
| `make test` | Python tests and 50 RTL tests pass | ~4 min the first time (Verilator builds), ~1 min after |
| `make test-repro` | `check_repro: OK, seed 1, … identical` | ~20 s |

## 7. Optional reproductions

| Command | What it does | Time |
| --- | --- | --- |
| `make demo` | one BERT-head GEMM on the RTL: NumPy check, measured vs predicted cycles | ~10 s after the first build |
| `make demo-waves` | VCD of one S = 4 tile, opened in GTKWave with `docs/demo/tile_s4.gtkw` | ~10 s |
| `make animate` | the same tile as an animated GIF, `docs/img/tile_s4.gif` (how to read it and view any test's waves: `docs/waveforms/README.md`) | seconds |
| `make waves-png` | GTKWave screenshot of that tile, `docs/img/waves_tile_s4.png` (needs `sudo apt install xvfb imagemagick`) | ~10 s |
| `make compile M=128 N=768 K=768` | a command file in `build/` + predicted cycles | seconds |
| `python3 scripts/measure/perf.py --quick` | 3 small benchmark shapes | seconds |
| `make campaign` | 1,000 random GEMMs | ~2 min |
| `make perf` | all 16 benchmark runs | ~30 min |
| `make synth` | ECP5 synthesis + place-and-route of `sa_pe`, `sa_array`, `sa_core`, `sa_top` | ~5 min |
| `make docs` / `make docs-check` | regenerate figures + results summary / check links and cited files | seconds |

`perf`, `campaign` and `synth` write new files under `results/` named after
your current commit. Keep them out of commits unless you mean to record a new
result (`git status` shows them; `git clean -n results/` lists them).

## 8. Optional: SKY130 with Docker + LibreLane

```bash
sudo apt install -y docker.io
sudo usermod -aG docker "$USER"
newgrp docker
```
```bash
bash scripts/librelane/setup.sh
```

`setup.sh` pulls `ghcr.io/librelane/librelane:3.0.17` (about 7.5 GB) and the
SKY130 PDK into `~/.sysarray-pdk` (about 2.2 GB). The run behind the README's
timing reference (run 4):

```bash
python3 scripts/librelane/run.py --S 8 --period 15 --io-delay 30
```

About an hour on 4 cores; writes `results/asic/sa_array_S8_<sha>_15ns_io30.json`.
The best slew-repaired run (run 8) adds these settings (also recorded under
`config_overrides` in `results/asic/sa_array_S8_bbe0222_15ns_io30_nox1_margin_grttiming.json`):

```bash
python3 scripts/librelane/run.py --S 8 --period 15 --io-delay 30 --tag nox1_margin_grttiming \
  --set 'EXTRA_EXCLUDED_CELLS=["sky130_fd_sc_hd__clkdlybuf4s15_1","sky130_fd_sc_hd__clkdlybuf4s15_2","sky130_fd_sc_hd__clkdlybuf4s18_1","sky130_fd_sc_hd__clkdlybuf4s18_2","sky130_fd_sc_hd__clkdlybuf4s25_1","sky130_fd_sc_hd__clkdlybuf4s25_2","sky130_fd_sc_hd__clkdlybuf4s50_1","sky130_fd_sc_hd__clkdlybuf4s50_2","sky130_fd_sc_hd__buf_1","sky130_fd_sc_hd__clkbuf_1"]' \
  --set RUN_POST_GRT_DESIGN_REPAIR=true --set DESIGN_REPAIR_MAX_SLEW_PCT=40 \
  --set GRT_DESIGN_REPAIR_MAX_SLEW_PCT=40 --set RUN_POST_GRT_RESIZER_TIMING=true
```

Details: `scripts/librelane/README.md`.

## 9. Troubleshooting

- **`make check` says `FAIL verilator 5.020`:** that is Ubuntu's package in
  `/usr/bin`, found before your tools. `make check` prints where each
  Verilator is. Fix: `sudo apt remove -y verilator`, then `hash -r` and
  `make clean && make check`. RTL tests and `make demo` fail until this is
  fixed (the demo tests in `make test-py` report "simulation failed").
- **`make check` warns `nextpnr-ecp5 not found` with option A:** the OSS CAD
  Suite `bin/` is not on `PATH` (check the folder you unpacked it to and the
  `export PATH` line). Only `make synth` needs it.
- **cocotb errors about `libpython` or "cannot import cocotb":** the venv is
  not active, or `python3-dev` is missing, or the OSS CAD Suite environment
  script was sourced. Open a new terminal, `source .venv/bin/activate`, and
  append (not source) the tool path.
- **Strange build errors after switching tools:** run `make clean` (removes
  every `tb/*/sim_build/`) and re-run.
- **A random test failed:** the log prints `SYSARRAY_SEED=<n>`; replay it
  exactly with `SYSARRAY_SEED=<n> make test-rtl`.
- **`docker: permission denied`:** your user is not in the `docker` group
  yet; run `newgrp docker` or log out and in again.
- **`yowasp-nextpnr-ecp5` not found (option B):** the installer ran without
  the venv active; activate it and run `python3 -m pip install yowasp-nextpnr-ecp5`.

## 10. Every new terminal

Option A (OSS CAD Suite):

```bash
cd "$HOME/sysarray" && source .venv/bin/activate && export PATH="$PATH:$HOME/tools/oss-cad-suite/bin" && make check
```

Option B (`scripts/install_eda.sh`):

```bash
cd "$HOME/sysarray" && source .venv/bin/activate && export PATH="$PATH:$HOME/.local/eda/bin" && make check
```

To make it permanent, add the `export PATH=...` line for your option to
`~/.bashrc`.
