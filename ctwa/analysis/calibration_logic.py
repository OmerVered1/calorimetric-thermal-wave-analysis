"""Page logic of app/calibration/page.tsx (rows, reference picker, lag source). No Qt."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ctwa.analysis.calibration import device_lag_from_reference, true_lag_for_alpha
from ctwa.analysis.jsmath import js_div, js_number_to_string, js_to_fixed
from ctwa.analysis.types import LagFit, LagPoint

TEMP_SPREAD_WARN_C = 30
DIRECT_PERIOD_LO = 0.8
DIRECT_PERIOD_HI = 1.25


def _finite(x) -> bool:
    return x is not None and math.isfinite(x)


def temp_key(v: Optional[float]) -> str:
    """String(a.temperature_c): the one key shared by the temperature combos and the row filters."""
    return "" if v is None else js_number_to_string(v)


def label_of(a: dict) -> str:
    parts = [a.get("model_name"), a.get("test_date")]
    if a.get("temperature_c") is not None:
        parts.append(f"{js_number_to_string(a['temperature_c'])}°C")
    if a.get("period_t") is not None:
        parts.append(f"T={js_to_fixed(a['period_t'], 0)}s")
    parts.append(a.get("analysis_mode"))
    return f"{' | '.join('' if p is None else str(p) for p in parts)} #{a['id']}"


def num(v, d: int = 2) -> str:
    return js_to_fixed(v, d) if _finite(v) else "—"


def split_rows(rows: List[dict]) -> Tuple[List[dict], List[dict], Dict[int, List[int]]]:
    refs = [a for a in rows if a.get("is_reference")]
    non_refs = [a for a in rows if not a.get("is_reference") and a.get("calibrated_from_id") is None]
    copies: Dict[int, List[int]] = {}
    for a in rows:
        src = a.get("calibrated_from_id")
        if src is None:
            continue
        copies.setdefault(src, []).append(a["id"])
    return refs, non_refs, copies


def all_materials(rows: List[dict]) -> List[str]:
    return sorted({a["model_name"] for a in rows if a.get("model_name")})


def _sorted_keys(keys) -> List[str]:
    return sorted(set(keys), key=lambda k: float(k))


def temps_for(non_refs: List[dict], material: str) -> List[str]:
    if not material:
        return []
    return _sorted_keys(temp_key(a["temperature_c"]) for a in non_refs
                        if a.get("model_name") == material and a.get("temperature_c") is not None)


def ref_temps(refs: List[dict], material: str) -> List[str]:
    return _sorted_keys(temp_key(r["temperature_c"]) for r in refs
                        if (material == "" or r.get("model_name") == material)
                        and r.get("temperature_c") is not None)


@dataclass
class RefLag:
    ref: dict
    lag: Optional[float]
    true_lag: Optional[float]


def ref_lags(refs: List[dict], method: str) -> List[RefLag]:
    out = []
    for r in refs:
        k = r.get("reference_alpha_mm2s")
        out.append(RefLag(r, None if k is None else device_lag_from_reference(r, k, method),
                          None if k is None else true_lag_for_alpha(r, k, method)))
    return out


def selected_lags(rl: List[RefLag], ids) -> List[RefLag]:
    # Deviation from the TS: a reference without a usable period is left out (the TS would fit it as 0).
    return [x for x in rl if x.ref["id"] in ids and _finite(x.lag)
            and _finite(x.ref.get("period_t")) and x.ref["period_t"] > 0]


@dataclass
class PickerRow:
    ref: dict
    lag: Optional[float]
    true_lag: Optional[float]
    d_t: Optional[float]
    d_p: Optional[float]


def picker_rows(rl: List[RefLag], target: Optional[dict], material: str, temp: str,
                near_only: bool, near_pct, sort: str) -> List[PickerRow]:
    pct = float("nan") if near_pct is None else float(near_pct)
    t_temp = target.get("temperature_c") if target else None
    t_per = target.get("period_t") if target else None
    rows: List[PickerRow] = []
    for x in rl:
        r = x.ref
        d_t = r["temperature_c"] - t_temp if t_temp is not None and r.get("temperature_c") is not None else None
        d_p = r["period_t"] - t_per if t_per is not None and r.get("period_t") is not None else None
        if material != "" and r.get("model_name") != material:
            continue
        if temp != "" and temp_key(r.get("temperature_c")) != temp:
            continue
        if near_only and t_per is not None and math.isfinite(pct) and pct > 0:
            if r.get("period_t") is None:
                continue
            ratio = js_div(r["period_t"], t_per)
            if ratio < 1 - pct / 100 or ratio > 1 + pct / 100:
                continue
        rows.append(PickerRow(r, x.lag, x.true_lag, d_t, d_p))

    def by(v):
        return math.inf if v is None else abs(v)

    if sort == "nearPeriod":
        return sorted(rows, key=lambda x: by(x.d_p))
    if sort == "nearTemp":
        return sorted(rows, key=lambda x: by(x.d_t))
    return sorted(rows, key=lambda x: x.ref.get("period_t") or 0)


def temp_spread(sel: List[RefLag]) -> Optional[float]:
    temps = [x.ref["temperature_c"] for x in sel if _finite(x.ref.get("temperature_c"))]
    if len(temps) < 2:
        return None
    return max(temps) - min(temps)


def mark_warnings(selected_rows: List[dict]) -> dict:
    materials = list(dict.fromkeys(a.get("model_name") for a in selected_rows))
    temps = [a["temperature_c"] for a in selected_rows if _finite(a.get("temperature_c"))]
    spread = max(temps) - min(temps) if len(temps) >= 2 else 0
    return {"mixed_materials": materials if len(materials) > 1 else None,
            "temp_spread": spread if spread > TEMP_SPREAD_WARN_C else None}


def active_fit(fits: List[LagFit], model_kind: Optional[str]) -> Optional[LagFit]:
    if not fits:
        return None
    if model_kind:
        for f in fits:
            if f.kind == model_kind:
                return f
    return fits[0]


def active_source(user: Optional[str], fit: Optional[LagFit]) -> str:
    if user is not None:
        return user
    return "curve" if fit else "direct"


def direct_lag(sel: List[RefLag]) -> Optional[float]:
    if not sel:
        return None
    s = 0.0
    for x in sel:
        s += x.lag
    return s / len(sel)


def direct_mean_period(sel: List[RefLag]) -> Optional[float]:
    ps = [x.ref["period_t"] for x in sel if _finite(x.ref.get("period_t"))]
    if not ps:
        return None
    s = 0.0
    for v in ps:
        s += v
    return s / len(ps)


@dataclass
class Applied:
    lag: float
    out_of_range: bool
    period_mismatch: bool
    ratio: Optional[float]


def applied_lag(target: Optional[dict], source: str, fit: Optional[LagFit],
                d_lag: Optional[float], d_mean_p: Optional[float]) -> Optional[Applied]:
    if not target or not _finite(target.get("period_t")):
        return None
    p = target["period_t"]
    if source == "direct":
        if not _finite(d_lag):
            return None
        ratio = p / d_mean_p if d_mean_p is not None and d_mean_p > 0 else None
        return Applied(d_lag, False,
                       ratio is not None and (ratio < DIRECT_PERIOD_LO or ratio > DIRECT_PERIOD_HI), ratio)
    if fit is None:
        return None
    lag = fit.predict(p)
    if not math.isfinite(lag):
        return None
    return Applied(lag, p < fit.p_min or p > fit.p_max, False, None)


def fit_points(sel: List[RefLag]) -> List[LagPoint]:
    return [LagPoint(period=x.ref["period_t"], lag=x.lag) for x in sel]


def curve_points(fit: LagFit, n: int = 120) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for i in range(n):
        p = fit.p_min * (fit.p_max / fit.p_min) ** (i / (n - 1))
        v = fit.predict(p)
        if math.isfinite(v):
            xs.append(p)
            ys.append(v)
    return xs, ys
