"""Shared build-and-run helper for every cocotb testbench (decision D-007).

A pytest launcher ``tb/<block>/test_<block>.py`` calls :func:`run` with the RTL
sources, the top module and its parameters. :func:`run` builds the design with
Verilator through ``cocotb_tools.runner`` and runs the cocotb module
``tb/<block>/cocotb_<block>.py`` in the simulator.

Environment:
    SYSARRAY_SEED   integer seed to replay a run. If unset, a fresh seed is drawn.
                    Either way the seed is printed and passed to the simulator as
                    both cocotb's random seed and ``SYSARRAY_SEED``, so
                    :func:`tb.common.utils.get_rng` in the test sees the same value.
    SYSARRAY_PARAMS is set by :func:`run` (JSON of the HDL parameters) so cocotb
                    tests can read them with :func:`tb.common.utils.get_params`.
    SYSARRAY_WAVES  set to 1 to dump a waveform (VCD) into the build directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path

from cocotb_tools.runner import get_runner

REPO_ROOT = Path(__file__).resolve().parents[2]
RTL_DIR = REPO_ROOT / "rtl"
SIM = "verilator"


def rtl(*relpaths: str) -> list[Path]:
    """Paths of RTL files given relative to ``rtl/`` (for example ``"common/sa_reg.sv"``)."""
    paths = [RTL_DIR / p for p in relpaths]
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(p)
    return paths


def resolve_seed() -> int:
    """SYSARRAY_SEED if set, else a fresh 31-bit seed (always printed by :func:`run`)."""
    env = os.environ.get("SYSARRAY_SEED")
    if env is not None and env.strip() != "":
        return int(env, 0)
    return secrets.randbits(31)


def waves_enabled() -> bool:
    return os.environ.get("SYSARRAY_WAVES", "0") not in ("", "0")


def _param_tag(parameters: Mapping[str, object]) -> str:
    """Short, stable directory tag so different parameter sets never share a build."""
    if not parameters:
        return "default"
    text = ",".join(f"{k}={parameters[k]}" for k in sorted(parameters))
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def build_dir_for(block_dir: Path, toplevel: str, parameters: Mapping[str, object]) -> Path:
    """Build directory used by :func:`run` (results.xml lives there)."""
    return block_dir / "sim_build" / f"{toplevel}_{_param_tag(dict(parameters))}"


def run(
    *,
    toplevel: str,
    sources: Sequence[Path],
    test_module: str,
    block_dir: Path,
    parameters: Mapping[str, object] | None = None,
    testcase: str | Sequence[str] | None = None,
    defines: Mapping[str, object] | None = None,
) -> int:
    """Build ``toplevel`` from ``sources`` and run cocotb module ``test_module``.

    Args:
        toplevel: name of the top-level HDL module.
        sources: SystemVerilog files, in compile order.
        test_module: fully qualified module of the cocotb tests (``tb.<block>.cocotb_<block>``),
            importable because pytest.ini puts the repo root on ``sys.path`` and the
            cocotb runner forwards ``sys.path`` to the simulator as PYTHONPATH.
        block_dir: testbench directory (``Path(__file__).parent``); builds, waves and
            results.xml go under ``<block_dir>/sim_build/<toplevel>_<param tag>/``.
        parameters: top-level HDL parameters, passed to Verilator as ``-G``.
        testcase: optional subset of cocotb test names to run.
        defines: Verilog defines (e.g. {"SA_ECP5_DSP": 1} for the DSP form of sa_pe).

    Returns:
        The seed used, so the launcher can include it in messages.

    Raises (through cocotb_tools under pytest) on any build error or failed test.
    """
    params = dict(parameters or {})
    seed = resolve_seed()
    waves = waves_enabled()
    defs = dict(defines or {})
    build_dir = build_dir_for(
        block_dir, toplevel, {**params, **{f"def_{k}": v for k, v in defs.items()}}
    )
    print(f"[sysarray] {toplevel} params={params} SYSARRAY_SEED={seed} waves={waves}")
    print(f"[sysarray] replay with: SYSARRAY_SEED={seed} make test-rtl")

    runner = get_runner(SIM)
    runner.build(
        sources=list(sources),
        includes=sorted({str(Path(s).parent) for s in sources}),
        hdl_toplevel=toplevel,
        parameters=params,
        defines=defs,
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        waves=waves,
        always=True,
    )
    # Never let a stale results.xml from an earlier run be read as this run's result
    # (e.g. if the simulator crashes before writing it).
    (build_dir / "results.xml").unlink(missing_ok=True)
    runner.test(
        test_module=test_module,
        hdl_toplevel=toplevel,
        test_dir=build_dir,
        build_dir=build_dir,
        testcase=testcase,
        seed=seed,
        waves=waves,
        extra_env={"SYSARRAY_SEED": str(seed), "SYSARRAY_PARAMS": json.dumps(params)},
        results_xml=str(build_dir / "results.xml"),
    )
    return seed
