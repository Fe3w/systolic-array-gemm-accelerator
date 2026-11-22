"""Compile one GEMM shape to a command file: python3 -m sysarray.cli M N K [options].

Writes JSON with the encoded commands (hex, one 93-bit word each), the tiler's
traffic statistics and the predictor's output (labelled "predicted
(analytical)"). Operand values do not change the program, so they are not
needed: the tiler is run on zero matrices of the requested shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

import numpy as np

from sysarray import predict, tiler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m sysarray.cli")
    ap.add_argument("M", type=int)
    ap.add_argument("N", type=int)
    ap.add_argument("K", type=int)
    ap.add_argument("--S", type=int, default=8)
    ap.add_argument("--order", choices=("A", "B"), default="A")
    ap.add_argument("--m-c", type=int, default=None)
    ap.add_argument("--latency", type=int, default=3, help="memory read latency for predict()")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    a = np.zeros((args.M, args.K), dtype=np.int64)
    b = np.zeros((args.K, args.N), dtype=np.int64)
    prog = tiler.tile(a, b, s=args.S, order=args.order, m_c=args.m_c)
    pred = predict.predict(prog.commands, s=args.S, read_latency=args.latency,
                           useful_macs=prog.stats.useful_macs)  # fmt: skip
    doc = {
        "M": args.M, "N": args.N, "K": args.K, "S": args.S, "order": args.order,
        "commands_hex": [f"{c.encode():024x}" for c in prog.commands],
        "stats": asdict(prog.stats),
        "predicted": {"label": "predicted (analytical)", "read_latency": args.latency,
                      "cycles_total": pred.cycles_total, "cycles_dma": pred.cycles_dma,
                      "cycles_compute": pred.cycles_compute, "macs_issued": pred.macs_issued,
                      "utilization": pred.utilization},
    }  # fmt: skip
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"{args.out}: {len(prog.commands)} commands, predicted (analytical) "
          f"{pred.cycles_total} cycles")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
