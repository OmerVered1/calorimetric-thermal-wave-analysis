"""Math.cos and Math.sin as V8 computes them (fdlibm), bit for bit.

The platform libm (and numpy's SIMD loops) differ from V8's fdlibm port in the
last bit for about 5 % of arguments. That is harmless for a well-conditioned
fit, but a fit of a constant signal returns pure rounding noise, and the golden
numbers of the webapp contain that noise. So the sine and cosine that feed the
least-squares fits and the Fourier sums are the fdlibm ones.

The medium-size argument reduction is vectorised with numpy (|x| up to
2^19 pi/2, about 8e5 rad, far beyond any argument in the analysis); beyond that
the platform libm is used.
"""

from __future__ import annotations

import math

import numpy as np

_S1 = -1.66666666666666324348e-01
_S2 = 8.33333333332248946124e-03
_S3 = -1.98412698298579493134e-04
_S4 = 2.75573137070700676789e-06
_S5 = -2.50507602534068634195e-08
_S6 = 1.58969099521155010221e-10
_C1 = 4.16666666666666019037e-02
_C2 = -1.38888888888741095749e-03
_C3 = 2.48015872894767294178e-05
_C4 = -2.75573143513906633035e-07
_C5 = 2.08757232129817482790e-09
_C6 = -1.13596475577881948265e-11
_INVPIO2 = 6.36619772367581382433e-01
_PIO2_1 = 1.57079632673412561417e+00
_PIO2_1T = 6.07710050650619224932e-11
_PIO2_2 = 6.07710050630396597660e-11
_PIO2_2T = 2.02226624879595063154e-21
_PIO2_3 = 2.02226624871116645580e-21
_PIO2_3T = 8.47842766036889956997e-32

_NPIO2_HW = np.array([
    0x3FF921FB, 0x400921FB, 0x4012D97C, 0x401921FB, 0x401F6A7A, 0x4022D97C,
    0x4025FDBB, 0x402921FB, 0x402C463A, 0x402F6A7A, 0x4031475C, 0x4032D97C,
    0x40346B9C, 0x4035FDBB, 0x40378FDB, 0x403921FB, 0x403AB41B, 0x403C463A,
    0x403DD85A, 0x403F6A7A, 0x40407E4C, 0x404147AC, 0x4042106C, 0x4042D97C,
    0x4043A28C, 0x40446B9C, 0x404534AC, 0x4045FDBB, 0x4046C6CB, 0x40478FDB,
    0x404858EB, 0x404921FB], dtype=np.int64)


_SPLIT = 134217729.0  # 2^27 + 1 (Veltkamp)


def _fma(a, b, c):
    """a*b + c with one rounding (the compiled V8 fuses these on arm64).

    Exact product by Dekker's two-product, then the three terms are summed
    with a two-sum; correct except in astronomically rare double-rounding ties.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    p = a * b
    ta = _SPLIT * a
    ah = ta - (ta - a)
    al = a - ah
    tb = _SPLIT * b
    bh = tb - (tb - b)
    bl = b - bh
    e = ((ah * bh - p) + ah * bl + al * bh) + al * bl
    s = p + c
    bb = s - p
    t = (p - (s - bb)) + (c - bb)
    return s + (t + e)


def _high(x: np.ndarray) -> np.ndarray:
    """High 32 bits of each double, as a signed int64 (GET_HIGH_WORD)."""
    return (np.ascontiguousarray(x).view(np.int64) >> 32)


def _kernel_sin(x: np.ndarray, y: np.ndarray, iy: bool) -> np.ndarray:
    ix = _high(x) & 0x7FFFFFFF
    z = x * x
    v = z * x
    r = _fma(z, _fma(z, _fma(z, _fma(z, _S6, _S5), _S4), _S3), _S2)
    if not iy:
        out = _fma(v, _fma(z, r, _S1), x)
    else:
        inner = _fma(0.5, y, -(v * r))
        inner = _fma(z, inner, -y)
        inner = _fma(-v, _S1, inner)
        out = x - inner
    return np.where(ix < 0x3E400000, x, out)  # |x| < 2^-27: sin x = x


def _kernel_cos(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    ix = _high(x) & 0x7FFFFFFF
    z = x * x
    r = z * _fma(z, _fma(z, _fma(z, _fma(z, _fma(z, _C6, _C5), _C4), _C3), _C2), _C1)
    zr_xy = _fma(z, r, -(x * y))
    small = 1.0 - (0.5 * z - zr_xy)
    qx = np.where(ix > 0x3FE90000, 0.28125,
                  ((ix - 0x00200000) << 32).astype(np.int64).view(np.float64))
    big = (1.0 - qx) - ((0.5 * z - qx) - zr_xy)
    out = np.where(ix < 0x3FD33333, small, big)
    return np.where(ix < 0x3E400000, 1.0, out)  # |x| < 2^-27: cos x = 1


def _rem_pio2(x: np.ndarray):
    """(n, y0, y1) for |x| <= 2^19 pi/2 (the small and medium branches of fdlibm)."""
    hx = _high(x)
    ix = hx & 0x7FFFFFFF
    pos = hx >= 0

    # |x| <= pi/4: no reduction
    n0 = np.zeros(x.shape, dtype=np.int64)

    # |x| < 3pi/4: n = +-1
    zp = x - _PIO2_1
    zn = x + _PIO2_1
    y0a_p = zp - _PIO2_1T
    y1a_p = (zp - y0a_p) - _PIO2_1T
    y0a_n = zn + _PIO2_1T
    y1a_n = (zn - y0a_n) + _PIO2_1T
    zp2 = zp - _PIO2_2
    y0b_p = zp2 - _PIO2_2T
    y1b_p = (zp2 - y0b_p) - _PIO2_2T
    zn2 = zn + _PIO2_2
    y0b_n = zn2 + _PIO2_2T
    y1b_n = (zn2 - y0b_n) + _PIO2_2T
    special = ix == 0x3FF921FB
    y0_s = np.where(pos, np.where(special, y0b_p, y0a_p), np.where(special, y0b_n, y0a_n))
    y1_s = np.where(pos, np.where(special, y1b_p, y1a_p), np.where(special, y1b_n, y1a_n))
    n_s = np.where(pos, 1, -1)

    # medium: |x| <= 2^19 pi/2
    t = np.abs(x)
    n = _fma(t, _INVPIO2, 0.5).astype(np.int64)
    fn = n.astype(np.float64)
    r = _fma(-fn, _PIO2_1, t)
    w = fn * _PIO2_1T
    j = ix >> 20
    y0 = r - w
    quick = (n < 32) & (ix != _NPIO2_HW[np.clip(n - 1, 0, 31)])
    i = j - ((_high(y0) >> 20) & 0x7FF)
    second = (~quick) & (i > 16)
    t2 = r
    w2 = fn * _PIO2_2
    r2 = t2 - w2
    w2 = _fma(fn, _PIO2_2T, -((t2 - r2) - w2))
    y0_2 = r2 - w2
    i2 = j - ((_high(y0_2) >> 20) & 0x7FF)
    third = second & (i2 > 49)
    t3 = r2
    w3 = fn * _PIO2_3
    r3 = t3 - w3
    w3 = _fma(fn, _PIO2_3T, -((t3 - r3) - w3))
    y0_3 = r3 - w3
    r = np.where(second, np.where(third, r3, r2), r)
    w = np.where(second, np.where(third, w3, w2), w)
    y0 = np.where(second, np.where(third, y0_3, y0_2), y0)
    y1 = (r - y0) - w
    y0_m = np.where(pos, y0, -y0)
    y1_m = np.where(pos, y1, -y1)
    n_m = np.where(pos, n, -n)

    small = ix <= 0x3FE921FB
    mid = ix < 0x4002D97C
    y0o = np.where(small, x, np.where(mid, y0_s, y0_m))
    y1o = np.where(small, 0.0, np.where(mid, y1_s, y1_m))
    no = np.where(small, n0, np.where(mid, n_s, n_m))
    return no, y0o, y1o


def _trig(x: np.ndarray, want_cos: bool, want_sin: bool):
    """(cos, sin) of x, each None when not wanted; the reduction and kernels run once."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    out_c = np.empty(x.shape, dtype=np.float64) if want_cos else None
    out_s = np.empty(x.shape, dtype=np.float64) if want_sin else None
    ix = _high(x) & 0x7FFFFFFF
    ok = ix <= 0x413921FB  # finite, |x| <= 2^19 pi/2
    with np.errstate(all="ignore"):
        if ok.any():
            xs = x[ok]
            n, y0, y1 = _rem_pio2(xs)
            k = n & 3
            ks0 = _kernel_sin(y0, y1, True)
            kc0 = _kernel_cos(y0, y1)
            if want_cos:
                out_c[ok] = np.where(k == 0, kc0, np.where(k == 1, -ks0, np.where(k == 2, -kc0, ks0)))
            if want_sin:
                # |x| <= pi/4 uses the kernel on x itself (iy = 0)
                direct = (_high(xs) & 0x7FFFFFFF) <= 0x3FE921FB
                ks_direct = _kernel_sin(xs, np.zeros_like(xs), False)
                out_s[ok] = np.where(direct, ks_direct,
                                     np.where(k == 0, ks0, np.where(k == 1, kc0, np.where(k == 2, -ks0, -kc0))))
    bad = ~ok
    if bad.any():
        for idx in np.flatnonzero(bad):
            v = float(x[idx])
            nonfinite = v != v or v in (math.inf, -math.inf)
            if want_cos:
                out_c[idx] = math.nan if nonfinite else math.cos(v)
            if want_sin:
                out_s[idx] = math.nan if nonfinite else math.sin(v)
    return out_c, out_s


def cos_array(x) -> np.ndarray:
    """Math.cos of every element (bit-exact with V8 up to |x| = 2^19 pi/2)."""
    return _trig(np.asarray(x, dtype=np.float64), True, False)[0]


def sin_array(x) -> np.ndarray:
    """Math.sin of every element (bit-exact with V8 up to |x| = 2^19 pi/2)."""
    return _trig(np.asarray(x, dtype=np.float64), False, True)[1]


def cos_sin_array(x):
    """(Math.cos, Math.sin) of every element, sharing the argument reduction."""
    return _trig(np.asarray(x, dtype=np.float64), True, True)
