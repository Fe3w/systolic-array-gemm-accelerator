"""Tests for the golden GEMM model against plain NumPy.

Every random test draws from a seeded generator. Set SYSARRAY_SEED to replay.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from sysarray import golden

INT8_MIN, INT8_MAX = -128, 127
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


def _seed() -> int:
    env = os.environ.get("SYSARRAY_SEED")
    return int(env) if env is not None else 20261112


@pytest.fixture
def rng() -> np.random.Generator:
    seed = _seed()
    print(f"SYSARRAY_SEED={seed}")
    return np.random.default_rng(seed)


def _rand_int8(rng: np.random.Generator, shape: tuple[int, int]) -> np.ndarray:
    return rng.integers(INT8_MIN, INT8_MAX + 1, size=shape, dtype=np.int64).astype(np.int8)


def _reference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Plain NumPy int64 matmul, independent of the golden model."""
    return np.matmul(a.astype(np.int64), b.astype(np.int64))


SHAPES = [
    (1, 1, 1),
    (1, 8, 1),
    (8, 1, 8),
    (4, 4, 4),
    (8, 8, 8),
    (3, 5, 7),
    (13, 9, 11),
    (17, 23, 29),
    (100, 37, 53),
    (64, 64, 64),
]


@pytest.mark.parametrize(("m", "n", "k"), SHAPES)
def test_random_matches_numpy(rng: np.random.Generator, m: int, n: int, k: int) -> None:
    a = _rand_int8(rng, (m, k))
    b = _rand_int8(rng, (k, n))
    c = golden.gemm(a, b)
    assert c.dtype == np.int32
    assert c.shape == (m, n)
    # No overflow is possible at these K, so wrap == exact.
    np.testing.assert_array_equal(c.astype(np.int64), _reference(a, b))


@pytest.mark.parametrize("value", [INT8_MIN, INT8_MAX])
def test_constant_corners(value: int) -> None:
    k = 77
    a = np.full((5, k), value, dtype=np.int8)
    b = np.full((k, 6), INT8_MIN, dtype=np.int8)
    expected = np.full((5, 6), k * value * INT8_MIN, dtype=np.int64)
    np.testing.assert_array_equal(golden.gemm(a, b).astype(np.int64), expected)


def test_minus128_squared_single() -> None:
    a = np.array([[INT8_MIN]], dtype=np.int8)
    b = np.array([[INT8_MIN]], dtype=np.int8)
    assert golden.gemm(a, b)[0, 0] == 16384


def test_mixed_signs_cancel() -> None:
    a = np.array([[INT8_MIN, INT8_MAX, INT8_MIN, INT8_MAX]], dtype=np.int8)
    b = np.array([[1], [1], [-1], [-1]], dtype=np.int8)
    assert golden.gemm(a, b)[0, 0] == 0


def test_max_safe_k() -> None:
    # |C| <= K * 2**14 <= 2**31 - 1  =>  K <= 131071
    assert golden.max_safe_k() == 131071
    assert golden.max_safe_k(data_w=8, acc_w=32) == 131071
    assert golden.max_safe_k(data_w=4, acc_w=16) == (2**15 - 1) // 2**6


def test_max_safe_k_is_tight() -> None:
    k = golden.max_safe_k()
    assert k * 2**14 <= INT32_MAX
    assert (k + 1) * 2**14 > INT32_MAX


def test_overflow_wraps_like_int32() -> None:
    """K = max_safe_k + 1 rows of (-128)*(-128) = 2**31 exactly -> wraps to -2**31."""
    k = golden.max_safe_k() + 1
    a = np.full((1, k), INT8_MIN, dtype=np.int8)
    b = np.full((k, 1), INT8_MIN, dtype=np.int8)
    c = golden.gemm(a, b, semantics="wrap")
    assert c[0, 0] == INT32_MIN
    # Same result as NumPy's own int32 arithmetic.
    exact = int(_reference(a, b)[0, 0])
    assert exact == 2**31
    assert c[0, 0] == np.array([exact], dtype=np.int64).astype(np.int32)[0]


def test_overflow_wrap_random_large_values(rng: np.random.Generator) -> None:
    """Wrap result equals the exact sum reduced modulo 2**32 into int32 range."""
    k = 3 * golden.max_safe_k()
    a = rng.choice(np.array([INT8_MIN, INT8_MAX], dtype=np.int8), size=(2, k))
    b = rng.choice(np.array([INT8_MIN, INT8_MAX], dtype=np.int8), size=(k, 2))
    exact = _reference(a, b)
    wrapped = ((exact + 2**31) % 2**32) - 2**31
    np.testing.assert_array_equal(golden.gemm(a, b).astype(np.int64), wrapped)


def test_saturate_semantics_clamps() -> None:
    k = golden.max_safe_k() + 1
    a = np.full((1, k), INT8_MIN, dtype=np.int8)
    b = np.full((k, 1), INT8_MIN, dtype=np.int8)
    assert golden.gemm(a, b, semantics="saturate")[0, 0] == INT32_MAX
    b_neg = np.full((k, 1), INT8_MAX, dtype=np.int8)
    assert golden.gemm(a, b_neg, semantics="saturate")[0, 0] == max(INT32_MIN, -128 * 127 * k)


def test_rejects_out_of_range_values() -> None:
    a = np.array([[128]], dtype=np.int64)
    b = np.array([[1]], dtype=np.int64)
    with pytest.raises(ValueError, match="int8"):
        golden.gemm(a, b)
    with pytest.raises(ValueError, match="int8"):
        golden.gemm(b, np.array([[-129]], dtype=np.int64))


def test_accepts_in_range_wider_dtypes() -> None:
    a = np.array([[-128, 127]], dtype=np.int64)
    b = np.array([[2], [3]], dtype=np.int32)
    assert golden.gemm(a, b)[0, 0] == -256 + 381


def test_rejects_bad_shapes_and_types() -> None:
    with pytest.raises(ValueError, match="inner"):
        golden.gemm(np.zeros((2, 3), np.int8), np.zeros((4, 2), np.int8))
    with pytest.raises(ValueError, match="2-D"):
        golden.gemm(np.zeros((3,), np.int8), np.zeros((3, 2), np.int8))
    with pytest.raises(TypeError, match="integer"):
        golden.gemm(np.zeros((1, 1), np.float32), np.zeros((1, 1), np.int8))
    with pytest.raises(ValueError, match="semantics"):
        golden.gemm(np.zeros((1, 1), np.int8), np.zeros((1, 1), np.int8), semantics="bogus")
