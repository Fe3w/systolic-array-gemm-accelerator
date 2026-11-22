# SysArray top-level Makefile. `make help` lists the targets; README.md says what each result is.
PYTHON ?= python3
RTL_DIRS := $(shell find rtl -type d 2>/dev/null)
RTL_SRCS := $(shell find rtl -name '*.sv' 2>/dev/null | sort)
VERILATOR_INC := $(addprefix -I,$(RTL_DIRS))

.PHONY: help check lint test test-py test-rtl test-repro measure-latency synth asic compile campaign perf docs docs-check demo demo-waves animate waves-png venv clean

help:
	@echo "make check     tool + package versions (fails if too old)"
	@echo "make lint      verilator --lint-only -Wall on every rtl/*.sv"
	@echo "make test      test-py + test-rtl"
	@echo "make test-py   pytest over compiler/"
	@echo "make test-rtl  pytest over tb/ (cocotb on Verilator)"
	@echo "make test-repro  run test-rtl twice with SYSARRAY_SEED=1, compare stimulus"
	@echo "make measure-latency  sa_array latency/T_tile for S=4,8 -> results/latency/"
	@echo "make synth     ECP5 synth + P&R for sa_pe, sa_array (S=8), sa_core (S=8) -> results/synth/"
	@echo "make demo      one BERT-head GEMM (128x64x768) on the RTL: NumPy check, measured vs predicted cycles"
	@echo "make demo-waves  VCD of one S=4 tile, opened in GTKWave with docs/demo/tile_s4.gtkw"
	@echo "make animate   animation of one S=4 tile from the simulation -> docs/img/tile_s4.gif"
	@echo "make waves-png  GTKWave screenshot of the same tile -> docs/img/waves_tile_s4.png"
	@echo "make docs      regenerate docs/img figures and docs/RESULTS_SUMMARY.md"
	@echo "make docs-check  links, cited results/ paths, spelling (codespell if installed)"
	@echo "make asic      SKY130 place-and-route of sa_array via LibreLane (PERIOD=20 S=8) -> results/asic/"
	@echo "make compile M=.. N=.. K=.. [S=8 ORDER=A]  compile a GEMM to build/prog_*.json"
	@echo "make campaign  long verification run (1000 GEMMs, S=8) -> results/verification/"
	@echo "make perf      benchmark the BRIEF shapes on the RTL (S=8, ~45 min) -> results/perf/"
	@echo "make venv      create .venv and install requirements (local use)"
	@echo "make clean     remove simulation output"

check:
	@PYTHON=$(PYTHON) bash scripts/check_env.sh

# Lint every module as its own top so each file is checked in full.
#  - Every rtl/ directory is an include/library path (-I = -y), so a module that
#    instantiates sa_reg finds rtl/common/sa_reg.sv by file name.
#  - Packages (files named *_pkg.sv) are passed first to every run.
#  - Verilator -Wall exits non-zero on any warning; waivers need an inline
#    /* verilator lint_off ... */ with a reason (docs/CONVENTIONS.md rule 9).
RTL_PKGS := $(filter %_pkg.sv,$(RTL_SRCS))
RTL_MODS := $(filter-out %_pkg.sv,$(RTL_SRCS))

lint:
	@if [ -z "$(RTL_SRCS)" ]; then echo "lint: no RTL yet"; exit 0; fi; \
	n=0; \
	for f in $(RTL_MODS); do \
	  top=$$(basename $$f .sv); \
	  echo "lint $$f (top $$top)"; \
	  verilator --lint-only -Wall $(VERILATOR_INC) --top-module $$top $(RTL_PKGS) $$f || exit 1; \
	  n=$$((n+1)); \
	done; \
	echo "lint: $$n module(s), 0 warnings"

test: test-py test-rtl

# pytest exits with 5 when it collects no tests; treat that as "nothing yet".
test-py:
	@$(PYTHON) -m pytest compiler scripts/librelane scripts/report scripts/demo scripts/waves -q; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "test-py: no tests yet"; exit 0; fi; exit $$rc

test-rtl:
	@$(PYTHON) -m pytest tb -q; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "test-rtl: no tests yet"; exit 0; fi; exit $$rc

test-repro:
	@PYTHON=$(PYTHON) bash scripts/check_repro.sh 1

measure-latency:
	$(PYTHON) scripts/measure/latency.py

synth:
	$(PYTHON) scripts/synth/ecp5.py --top sa_pe --S 0
	$(PYTHON) scripts/synth/ecp5.py --top sa_array --S 8
	$(PYTHON) scripts/synth/ecp5.py --top sa_core --S 8
	$(PYTHON) scripts/synth/ecp5.py --top sa_top --S 8

S ?= 8
ORDER ?= A
compile:
	@mkdir -p build
	PYTHONPATH=compiler $(PYTHON) -m sysarray.cli $(M) $(N) $(K) --S $(S) --order $(ORDER) --out build/prog_$(M)x$(N)x$(K)_S$(S)_$(ORDER).json

campaign:
	$(PYTHON) scripts/verify/campaign.py --n 1000 --S 8

docs:
	$(PYTHON) scripts/report/figures.py
	$(PYTHON) scripts/report/results_summary.py
	@# resume metrics: development repository only (not published)
	@if [ -f scripts/report/resume_metrics.py ]; then $(PYTHON) scripts/report/resume_metrics.py; fi

docs-check:
	$(PYTHON) scripts/report/check_docs.py
	@if command -v codespell >/dev/null; then codespell -L shotcut README.md docs/*.md docs/spec/*.md scripts/librelane/README.md && echo "codespell: clean"; else echo "codespell not installed: skipped"; fi

demo:
	$(PYTHON) scripts/demo/demo.py

demo-waves:
	$(PYTHON) scripts/demo/demo_waves.py

animate:
	$(PYTHON) scripts/demo/demo_waves.py --no-open
	$(PYTHON) scripts/report/animate_tile.py

waves-png:
	$(PYTHON) scripts/demo/demo_waves.py --no-open
	$(PYTHON) scripts/waves/gtkwave_screenshot.py

asic:
	bash scripts/librelane/setup.sh
	$(PYTHON) scripts/librelane/run.py --S $(or $(S),8) --period $(or $(PERIOD),20)

perf:
	$(PYTHON) scripts/measure/perf.py

venv:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.txt
	@echo "Now run: source .venv/bin/activate"

clean:
	find . -name sim_build -type d -prune -exec rm -rf {} +
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . \( -name '*.vcd' -o -name '*.fst' -o -name 'results.xml' \) -delete
