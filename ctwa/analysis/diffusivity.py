"""Thermal diffusivity from amplitudes and lag, and the data sync step.

Literal port of the parts of lib/analysis.ts of the webapp that every mode
shares: unit conversion and clock sync (syncAndFilterData), the Angstrom
formulas (calculateThermalDiffusivity) and the theoretical phase / lag for a
known alpha.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from ctwa.analysis.jsmath import array_max, array_min, js_div, js_log, js_number, js_sqrt
from ctwa.analysis.types import AnalysisParams, AnalysisResults, SyncedData

TIME_FACTORS: Dict[str, float] = {
    "Seconds": 1,
    "Minutes": 60,
    "Hours": 3600,
    "ms": 0.001,
}

POWER_FACTORS: Dict[str, float] = {
    "mW": 1,
    "Watts": 1000,
    "uW": 0.001,
}

_js_number = js_number  # kept for existing importers; the implementation lives in jsmath


def _hhmmss_to_seconds(hms: str) -> float:
    parts = [_js_number(p) for p in hms.split(":")]
    nan = math.nan
    h = parts[0]
    m = parts[1] if len(parts) > 1 else nan
    s = parts[2] if len(parts) > 2 else nan
    return h * 3600 + m * 60 + s


def sync_and_filter_data(
    cal_time: List[float],
    cal_value: List[float],
    src_time: List[float],
    src_value: List[float],
    params: AnalysisParams,
) -> SyncedData:
    """Unit conversions, clock sync, and the calorimeter filtered to the source's span (+-500 s)."""
    nan = math.nan  # JS: a unit name outside the table gives undefined, and t * undefined is NaN
    ctf = TIME_FACTORS.get(params.c80_time_unit, nan)
    cpf = POWER_FACTORS.get(params.c80_pwr_unit, nan)
    stf = TIME_FACTORS.get(params.src_time_unit, nan)
    spf = POWER_FACTORS.get(params.src_pwr_unit, nan)

    t_cal_raw = [t * ctf for t in cal_time]
    v_cal_raw = [v * cpf for v in cal_value]
    t_src_raw = [t * stf for t in src_time]
    v_src_all = [v * spf for v in src_value]

    day_offset = 0 if params.day_offset is None else params.day_offset
    clock_ahead = 0 if params.clock_ahead_s is None else params.clock_ahead_s
    offset = (
        _hhmmss_to_seconds(params.t_src)
        - _hhmmss_to_seconds(params.t_cal)
        + 86400 * day_offset
        - clock_ahead
    )
    t_src_sync = [t + offset for t in t_src_raw]

    src_min = array_min(t_src_sync) - 500
    src_max = array_max(t_src_sync) + 500

    t_cal: List[float] = []
    v_cal: List[float] = []
    for i in range(len(t_cal_raw)):
        if t_cal_raw[i] >= src_min and t_cal_raw[i] <= src_max:
            t_cal.append(t_cal_raw[i])
            v_cal.append(v_cal_raw[i])

    return SyncedData(t_src=t_src_sync, v_src=v_src_all, t_cal=t_cal, v_cal=v_cal)


def calculate_thermal_diffusivity(
    a1: float,
    a2: float,
    T: float,
    w: float,
    dt: float,
    params: AnalysisParams,
    t_min: float,
    t_max: float,
    marker_src: float,
    marker_src2: float,
    marker_cal: float,
) -> AnalysisResults:
    r1 = params.r1_mm / 1000
    r2 = params.r2_mm / 1000
    dr = r2 - r1

    phi = w * abs(dt)

    if a1 <= 0 or a2 <= 0 or r1 <= 0 or r2 <= 0:
        raise ValueError("Amplitudes and radii must be positive")

    # ln(A1 sqrt(r1) / A2 sqrt(r2)) must be positive; when it is not, alpha
    # combined is undefined (None) and the true ln is kept.
    ln_arg = (a1 / a2) * js_sqrt(r1 / r2)
    ln_val = js_log(ln_arg)
    ln_ok = ln_val > 0 and math.isfinite(ln_val)

    # Raw, combined method: alpha = w (r2-r1)^2 / (2 phi ln)
    alpha_combined_raw: Optional[float] = (
        js_div(w * dr * dr, 2 * phi * ln_val) if ln_ok else None
    )

    # Raw, phase-only method: alpha = (w/2) ((r2-r1)/phi)^2   (x*x is JS's x ** 2)
    q = js_div(dr, phi)
    alpha_phase_raw = (w / 2) * (q * q)

    lag = params.system_lag if params.use_calibration else 0.0
    dt_net = abs(dt) - lag
    phi_net = w * dt_net if dt_net > 0 else 0.0

    alpha_combined_cal: Optional[float] = -1.0 if ln_ok else None
    alpha_phase_cal = -1.0
    if dt_net > 0 and phi_net > 0:
        if ln_ok:
            alpha_combined_cal = js_div(w * dr * dr, 2 * phi_net * ln_val)
        qn = js_div(dr, phi_net)
        alpha_phase_cal = (w / 2) * (qn * qn)

    return AnalysisResults(
        amplitude_a1=a1,
        amplitude_a2=a2,
        period_t=T,
        frequency_f=js_div(1, T),
        angular_freq_w=w,
        raw_lag_dt=abs(dt),
        raw_phase_phi=phi,
        ln_term=ln_val,
        alpha_phase_raw=alpha_phase_raw,
        alpha_phase_cal=alpha_phase_cal,
        net_lag_dt=dt_net,
        net_phase_phi=phi_net,
        t_min=t_min,
        t_max=t_max,
        marker_src_time=marker_src,
        marker_src2_time=marker_src2,
        marker_cal_time=marker_cal,
        mean_peak_src=0.0,
        mean_trough_src=0.0,
        mean_peak_cal=0.0,
        mean_trough_cal=0.0,
        period_t_resp=None,
        frequency_f_resp=None,
        alpha_combined_raw=alpha_combined_raw,
        alpha_combined_cal=alpha_combined_cal,
    )


def theoretical_phase(alpha_mm2s: float, dr_mm: float, period_s: float) -> Optional[float]:
    """Phase lag (rad) the physics alone gives for a known alpha (mm^2/s)."""
    if not (alpha_mm2s > 0) or not (dr_mm > 0) or not (period_s > 0):
        return None
    alpha = alpha_mm2s * 1e-6  # mm^2/s -> m^2/s
    dr = dr_mm / 1000  # mm -> m
    w = (2 * math.pi) / period_s
    phi = dr * js_sqrt(js_div(w, 2 * alpha))
    return phi if math.isfinite(phi) else None


def theoretical_lag_dt(alpha_mm2s: float, dr_mm: float, period_s: float) -> Optional[float]:
    """The same as a time lag: dt = phi / w."""
    phi = theoretical_phase(alpha_mm2s, dr_mm, period_s)
    if phi is None:
        return None
    w = (2 * math.pi) / period_s
    dt = js_div(phi, w)
    return dt if math.isfinite(dt) else None
