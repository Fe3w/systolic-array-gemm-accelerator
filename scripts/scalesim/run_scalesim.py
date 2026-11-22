#!/usr/bin/env python3
"""Run SCALE-Sim v3 on the BRIEF §9.2 shapes with a SysArray-like config (M11).

SCALE-Sim needs its own environment (its NumPy pin differs from the repo's):
    python3 -m venv .venv-scalesim
    .venv-scalesim/bin/pip install scalesim==3.0.0 numpy==2.2.6
    .venv-scalesim/bin/python scripts/scalesim/run_scalesim.py
Configuration (results/scalesim/sysarray_s8_ws.cfg): 8 x 8 array, weight
stationary, SRAMs sized like SysArray's buffers (input 2 KiB, weight 1 KiB =
SCALE-Sim's minimum for SysArray's 64 B, accumulator 8 KiB), user interface
bandwidth 8 words/cycle (SysArray's DMA moves one 8-byte row per cycle).
--shapes selects a subset (the large BERT/ResNet shapes take SCALE-Sim far
longer than the RTL simulation). Outputs results/scalesim/COMPUTE_REPORT.csv
(copied from SCALE-Sim's run dir) plus the config, topology and layout files.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from scalesim.scale_sim import scalesim

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "scalesim"
SHAPES = {
    "sq8": (8, 8, 8),
    "sq16": (16, 16, 16),
    "sq64": (64, 64, 64),
    "sq256": (256, 256, 256),
    "bert_proj": (128, 768, 768),
    "bert_ffn_down": (128, 768, 3072),
    "bert_ffn_up": (128, 3072, 768),
    "r50_3x3": (3136, 64, 576),
    "r50_1x1": (3136, 256, 64),
    "odd": (100, 37, 53),
}
CFG = """[general]
run_name = sysarray_s8_ws

[architecture_presets]
ArrayHeight : 8
ArrayWidth : 8
IfmapSramSzkB : 2
FilterSramSzkB : 1
OfmapSramSzkB : 8
IfmapOffset : 0
FilterOffset : 10000000
OfmapOffset : 20000000
Bandwidth : 8
Dataflow : ws
ReadRequestBuffer : 32
WriteRequestBuffer : 32

[layout]
IfmapCustomLayout : False
IfmapSRAMBankBandwidth : 10
IfmapSRAMBankNum : 10
IfmapSRAMBankPort : 2
FilterCustomLayout : False
FilterSRAMBankBandwidth : 10
FilterSRAMBankNum : 10
FilterSRAMBankPort : 2

[sparsity]
SparsitySupport : false
SparseRep : ellpack_block
OptimizedMapping : false
BlockSize : 8
RandomNumberGeneratorSeed : 40

[run_presets]
InterfaceBandwidth : USER
UseRamulatorTrace : False
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shapes", default=",".join(SHAPES), help="comma-separated shape ids")
    ap.add_argument("--out", default=str(OUT), help="output directory")
    args = ap.parse_args()
    names = args.shapes.split(",")
    out = Path(args.out)
    shapes = {n: SHAPES[n] for n in names}
    out.mkdir(parents=True, exist_ok=True)
    cfg, topo, layout = out / "sysarray_s8_ws.cfg", out / "topology.csv", out / "layout.csv"
    cfg.write_text(CFG)
    topo.write_text("Layer, M, N, K,\n" + "".join(f"{n}, {m}, {nn}, {k},\n"
                                                 for n, (m, nn, k) in shapes.items()))  # fmt: skip
    # Custom layouts are off; SCALE-Sim still requires a layout file with one row per layer.
    layout.write_text("Layer, p1, p2, p3, p4, p5, p6, p7,\n"
                      + "".join(f"{n}, 1, 1, 1, 1, 1, 1, 1,\n" for n in shapes))  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp:
        sim = scalesim(save_disk_space=True, verbose=False, config=str(cfg), topology=str(topo),
                       layout=str(layout), input_type_gemm=True)  # fmt: skip
        sim.run_scale(top_path=tmp)
        report = next(Path(tmp).rglob("COMPUTE_REPORT.csv"))
        shutil.copy(report, out / "COMPUTE_REPORT.csv")
    print(f"scalesim: wrote {out / 'COMPUTE_REPORT.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
