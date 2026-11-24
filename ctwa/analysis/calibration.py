"""Reference-run calibration: literal port of lib/analysis.ts (calibrationBasis, trueLagForAlpha,
deviceLagFromReference, applyDeviceLag). Rows are dicts with the database column names."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


def _pos(x) -> bool:
    """JS `x > 0` for a number or null: NaN and None are false."""
    return x is not None and x > 0


@dataclass(frozen=True)
class AppliedLag:
    net_lag_dt: float
    net_phase_phi: float
    alpha_combined_cal: Optional[float]
    alpha_phase_cal: float


def calibration_basis(a: dict) -> Optional[Tuple[float, float]]:
    """(dr_m, w) or None when the geometry or frequency is unusable."""
    if a.get("r1_mm") is None or a.get("r2_mm") is None:
        return None
    r1 = a["r1_mm"] / 1000
    r2 = a["r2_mm"] / 1000
    dr = r2 - r1
    w = a.get("angular_freq_w")
    if not _pos(r1) or not _pos(r2) or not _pos(dr) or not _pos(w) or not math.isfinite(w):
        return None
    return dr, w


def true_lag_for_alpha(a: dict, known_alpha_mm2s, method: str = "phase") -> Optional[float]:
    basis = calibration_basis(a)
    if basis is None or not _pos(known_alpha_mm2s):
        return None
    dr, w = basis
    alpha = known_alpha_mm2s * 1e-6
    if method == "combined":
        ln = a.get("ln_term")
        if not _pos(ln) or not math.isfinite(ln):
            return None
        return (dr * dr) / (2 * alpha * ln)
    return dr / math.sqrt(2 * alpha * w)


def device_lag_from_reference(a: dict, known_alpha_mm2s, method: str = "phase") -> Optional[float]:
    true_lag = true_lag_for_alpha(a, known_alpha_mm2s, method)
    if true_lag is None or not math.isfinite(true_lag):
        return None
    raw = a.get("raw_lag_dt")
    if raw is None or not math.isfinite(raw):
        return None
    return raw - true_lag


def apply_device_lag(a: dict, lag) -> Optional[AppliedLag]:
    basis = calibration_basis(a)
    if basis is None or a.get("raw_lag_dt") is None or lag is None or not math.isfinite(lag):
        return None
    dr, w = basis
    net_lag = abs(a["raw_lag_dt"]) - lag
    if not net_lag > 0:
        return None
    phi = w * net_lag
    if not phi > 0:
        return None
    ln = a.get("ln_term")
    comb = (w * dr * dr) / (2 * phi * ln) if _pos(ln) and math.isfinite(ln) else None
    return AppliedLag(net_lag_dt=net_lag, net_phase_phi=phi, alpha_combined_cal=comb,
                      alpha_phase_cal=(w / 2) * (dr / phi) ** 2)
