"""pytest smoke test for the benchmark runner (tb/perf) on two tiny shapes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tb.common.runner import rtl, run
from tb.top.test_top import SOURCES


def test_perf_smoke(tmp_path: Path, monkeypatch) -> None:
    shapes = [{"shape_id": "t1", "M": 5, "N": 9, "K": 11, "order": "A", "m_c": None},
              {"shape_id": "t2", "M": 8, "N": 8, "K": 8, "order": "B", "m_c": 3}]  # fmt: skip
    monkeypatch.setenv("SYSARRAY_PERF_SHAPES", json.dumps(shapes))
    monkeypatch.setenv("SYSARRAY_RESULTS_DIR", str(tmp_path))
    run(toplevel="sa_top", sources=rtl(*SOURCES), test_module="tb.perf.cocotb_perf",
        block_dir=Path(__file__).parent, parameters={"S": 8})  # fmt: skip
    recs = [json.loads(x) for x in (tmp_path / "perf.jsonl").read_text().splitlines()]
    assert [r["shape_id"] for r in recs] == ["t1", "t2"]
    assert all(r["c_ok"] and r["cycles_total"] == r["predicted_cycles"] for r in recs)
    assert os.environ["SYSARRAY_RESULTS_DIR"] == str(tmp_path)
