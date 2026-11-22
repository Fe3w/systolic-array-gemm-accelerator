"""Golden reference model for SysArray's arithmetic.

C = A @ B with signed int8 A (M x K) and B (K x N), signed int32 C (M x N).

The sum is computed exactly in int64 by NumPy, then reduced to int32 with the
chosen semantics (decision D-004):

* ``"wrap"``     two's-complement wrap at 32 bits (what the RTL adder does,
                 and what NumPy int32 arithmetic does). Default.
* ``"saturate"`` clamp to [-2**31, 2**31 - 1]. Kept for comparison only.

Exactness of the int64 intermediate: each product is at most 2**14 in
magnitude, so int64 is exact for K < 2**49, far beyond any shape we use.
Wrapping the final int64 sum is identical to wrapping after every add,
because reduction modulo 2**32 commutes with addition.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import numpy.typing as npt

Semantics = Literal["wrap", "saturate"]

DATA_W = 8
ACC_W = 32


def max_safe_k(data_w: int = DATA_W, acc_w: int = ACC_W) -> int:
    """Largest K for which no signed acc_w-bit overflow is possible.

    The largest product magnitude is (-2**(data_w-1))**2 = 2**(2*data_w - 2).
    We need K * 2**(2*data_w - 2) <= 2**(acc_w - 1) - 1.
    For data_w=8, acc_w=32: (2**31 - 1) // 2**14 = 131071.
    """
    max_product = 2 ** (2 * data_w - 2)
    return (2 ** (acc_w - 1) - 1) // max_product


def _check_operand(x: npt.ArrayLike, name: str) -> np.ndarray:
    arr = np.asarray(x)
    if not np.issubdtype(arr.dtype, np.integer):
        raise TypeError(f"{name} must have an integer dtype, got {arr.dtype}")
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 2-D, got shape {arr.shape}")
    lo, hi = -(2 ** (DATA_W - 1)), 2 ** (DATA_W - 1) - 1
    if arr.size and (arr.min() < lo or arr.max() > hi):
        raise ValueError(f"{name} has values outside int8 range [{lo}, {hi}]")
    return arr.astype(np.int64)


def to_int32(x: npt.ArrayLike, semantics: Semantics = "wrap") -> np.ndarray:
    """Reduce exact int64 values to int32 with the given semantics."""
    v = np.asarray(x, dtype=np.int64)
    lo, hi = -(2 ** (ACC_W - 1)), 2 ** (ACC_W - 1) - 1
    if semantics == "wrap":
        return (((v - lo) % 2**ACC_W) + lo).astype(np.int32)
    if semantics == "saturate":
        return np.clip(v, lo, hi).astype(np.int32)
    raise ValueError(f"unknown semantics {semantics!r}; use 'wrap' or 'saturate'")


def gemm(a: npt.ArrayLike, b: npt.ArrayLike, semantics: Semantics = "wrap") -> np.ndarray:
    """Return C = A @ B as int32 using the given overflow semantics."""
    if semantics not in ("wrap", "saturate"):
        raise ValueError(f"unknown semantics {semantics!r}; use 'wrap' or 'saturate'")
    a64 = _check_operand(a, "A")
    b64 = _check_operand(b, "B")
    if a64.shape[1] != b64.shape[0]:
        raise ValueError(f"inner dimensions differ: A is {a64.shape}, B is {b64.shape}")
    return to_int32(a64 @ b64, semantics)
