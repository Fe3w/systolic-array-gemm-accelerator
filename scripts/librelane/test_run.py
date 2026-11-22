"""Unit tests for scripts/librelane/run.py's metrics summary (M12).

The fixture is a hand-written subset of LibreLane 3.0.17's final/metrics.json
key names (taken from a real run's file), with made-up values: the test checks
the parsing, not any result.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("ll_run", Path(__file__).with_name("run.py"))
assert _spec and _spec.loader
ll_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ll_run)

METRICS = {
    "design__die__area": 1000.5,
    "design__core__area": 800.25,
    "design__instance__area__stdcell": 400.0,
    "design__instance__count__stdcell": 1234,
    "design__instance__count__class:sequential_cell": 100,
    "design__instance__count__class:multi_input_combinational_cell": 900,
    "design__instance__utilization__stdcell": 0.5,
    "timing__setup__ws": -1.5,
    "timing__setup__tns": -20.0,
    "timing__hold__ws": 0.1,
    "timing__hold__tns": 0.0,
    "timing__setup__ws__corner:nom_tt_025C_1v80": 2.0,
    "timing__setup__ws__corner:max_ss_100C_1v60": -1.5,
    "timing__hold__ws__corner:nom_tt_025C_1v80": 0.3,
    "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0,
    "design__lvs_error__count": 0,
    "route__antenna_violation__count": 2,
    "route__drc_errors": 0,
    "power__total": 0.001,
    "flow__errors__count": 0,
}


def test_summary_fields() -> None:
    s = ll_run.summarize(METRICS, period_ns=10.0)
    assert s["area_um2"] == {"die": 1000.5, "core": 800.25, "stdcell": 400.0}
    assert s["cells"]["stdcell"] == 1234
    assert s["cells"]["sequential"] == 100
    assert s["timing_ns"]["setup_ws_worst_corner"] == -1.5
    assert s["timing_ns"]["setup_tns_worst_corner"] == -20.0
    assert s["timing_ns"]["setup_ws_by_corner"]["nom_tt_025C_1v80"] == 2.0
    assert s["timing_ns"]["hold_ws_by_corner"]["nom_tt_025C_1v80"] == 0.3
    assert s["signoff"]["antenna_violations"] == 2
    assert s["signoff"]["lvs_errors"] == 0


def test_fmax_from_slack() -> None:
    """Achieved frequency = 1 / (period - worst setup slack), per corner set."""
    s = ll_run.summarize(METRICS, period_ns=10.0)
    assert s["fmax_mhz"]["worst_corner"] == pytest.approx(1000 / 11.5, abs=0.01)
    assert s["fmax_mhz"]["nom_tt_025C_1v80"] == pytest.approx(1000 / 8.0, abs=0.01)


def test_missing_key_is_reported_not_invented() -> None:
    m = dict(METRICS)
    del m["timing__hold__tns"]
    s = ll_run.summarize(m, period_ns=10.0)
    assert s["timing_ns"]["hold_tns_worst_corner"] is None


LOG_TAIL = """\
[09:21:43] ERROR    The following error was encountered while    __main__.py:189
                    running the flow:
                    One or more deferred errors were
                    encountered:
                    Hold violations found in the following
                    corners:
                    * max_ss_100C_1v60
                    * nom_ss_100C_1v60
[09:21:43] ERROR    LibreLane will now quit.                     __main__.py:190
"""


def test_flow_error_extracted_from_log() -> None:
    """A run that fails sign-off still has metrics; the error text is recorded with them."""
    err = ll_run.flow_error(LOG_TAIL)
    assert err == ("One or more deferred errors were encountered: Hold violations found in the "
                   "following corners: * max_ss_100C_1v60 * nom_ss_100C_1v60")  # fmt: skip


def test_flow_error_none_when_clean() -> None:
    assert ll_run.flow_error("[09:00:00] INFO  Flow complete.\n") is None


def test_parse_overrides() -> None:
    """M12b: --set KEY=VALUE overrides LibreLane config keys; values are JSON when they parse."""
    got = ll_run.parse_overrides(["RUN_POST_GRT_DESIGN_REPAIR=true",
                                  'EXTRA_EXCLUDED_CELLS=["a", "b"]',
                                  "DESIGN_REPAIR_MAX_SLEW_PCT=30", "NAME=text"])  # fmt: skip
    assert got == {"RUN_POST_GRT_DESIGN_REPAIR": True, "EXTRA_EXCLUDED_CELLS": ["a", "b"],
                   "DESIGN_REPAIR_MAX_SLEW_PCT": 30, "NAME": "text"}  # fmt: skip


def test_parse_overrides_rejects_bad_key() -> None:
    with pytest.raises(ValueError, match="KEY=VALUE"):
        ll_run.parse_overrides(["no_equals_sign"])
