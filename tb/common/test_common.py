"""Simulator-free unit tests for the shared testbench helpers."""

from __future__ import annotations

import pytest

from tb.common import runner, utils


def test_signed_roundtrip() -> None:
    for width in (1, 8, 17, 32):
        lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
        for v in (lo, -1, 0, 1, hi):
            if width == 1 and v == 1:
                continue
            assert utils.to_signed(utils.to_unsigned(v, width), width) == v
    assert utils.to_unsigned(-128, 8) == 0x80
    assert utils.to_signed(0xFF, 8) == -1
    with pytest.raises(ValueError):
        utils.to_unsigned(256, 8)


def test_seed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSARRAY_SEED", "1234")
    assert runner.resolve_seed() == 1234
    assert utils.get_seed() == 1234
    monkeypatch.setenv("SYSARRAY_SEED", "0x10")
    assert runner.resolve_seed() == 16


def test_fresh_seed_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYSARRAY_SEED", raising=False)
    seed = runner.resolve_seed()
    assert 0 <= seed < 2**31


def test_rng_reproducible_and_salted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSARRAY_SEED", "1")
    a = [utils.get_rng("t").getrandbits(32) for _ in range(3)]
    b = [utils.get_rng("t").getrandbits(32) for _ in range(3)]
    c = utils.get_rng("other").getrandbits(32)
    assert a == b
    assert c != a[0]


def test_params_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSARRAY_PARAMS", '{"W": 8, "D": 3}')
    assert utils.get_params() == {"W": 8, "D": 3}


def test_param_tag_stable_and_distinct() -> None:
    assert runner._param_tag({"W": 8, "D": 1}) == runner._param_tag({"D": 1, "W": 8})
    assert runner._param_tag({"W": 8, "D": 1}) != runner._param_tag({"W": 8, "D": 2})
    assert runner._param_tag({}) == "default"


def test_pack_unpack_roundtrip() -> None:
    vals = [-128, 127, 0, -1]
    word = utils.pack(vals, 8)
    assert word == 0xFF_00_7F_80  # element 0 (-128 = 0x80) in the low byte
    assert utils.unpack(word, 8, 4) == vals
    big = [-(2**31), 2**31 - 1, 5]
    assert utils.unpack(utils.pack(big, 32), 32, 3) == big
