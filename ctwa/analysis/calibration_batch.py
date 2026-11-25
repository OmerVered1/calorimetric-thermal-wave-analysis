"""Batch calibration logic of app/calibration/page.tsx (batchRows, batchOk, buildCalibratedRow,
saveBatch reports). No Qt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ctwa.analysis.calibration import AppliedLag, apply_device_lag
from ctwa.analysis.calibration_logic import applied_lag, temp_key
from ctwa.analysis.lag_fit import serialize_direct, serialize_fit
from ctwa.analysis.types import LagFit


@dataclass
class BatchRow:
    a: dict
    existing: List[int]
    lag: Optional[float]
    result: Optional[AppliedLag]
    status: str  # "ok" | "outOfRange" | "notCalibratable"


def batch_targets(non_refs: List[dict], material: str, temp_key_: str) -> List[dict]:
    if not material:
        return []
    return [a for a in non_refs if a.get("model_name") == material
            and (temp_key_ == "" or temp_key(a.get("temperature_c")) == temp_key_)]


def batch_rows(targets: List[dict], source: str, fit: Optional[LagFit], d_lag: Optional[float],
               d_mean_p: Optional[float], copies: Dict[int, List[int]]) -> List[BatchRow]:
    rows: List[BatchRow] = []
    for a in targets:
        existing = list(copies.get(a["id"], []))
        ap = applied_lag(a, source, fit, d_lag, d_mean_p)
        if ap is None:
            rows.append(BatchRow(a, existing, None, None, "notCalibratable"))
            continue
        result = apply_device_lag(a, ap.lag)
        if result is None:
            rows.append(BatchRow(a, existing, ap.lag, None, "notCalibratable"))
            continue
        flagged = ap.out_of_range or ap.period_mismatch
        rows.append(BatchRow(a, existing, ap.lag, result, "outOfRange" if flagged else "ok"))
    return rows


def batch_calibratable(rows: List[BatchRow]) -> List[BatchRow]:
    return [r for r in rows if r.result is not None]


def batch_default_ids(rows: List[BatchRow]) -> List[int]:
    return [r.a["id"] for r in batch_calibratable(rows) if not r.existing]


def batch_ok(rows: List[BatchRow], picked: Optional[List[int]]) -> List[BatchRow]:
    cal = batch_calibratable(rows)
    if picked is None:
        return [r for r in cal if not r.existing]
    return [r for r in cal if r.a["id"] in picked]


def toggle_pick(picked: Optional[List[int]], default_ids: List[int], id_: int, on: bool) -> List[int]:
    base = list(default_ids if picked is None else picked)
    if on:
        return base if id_ in base else base + [id_]
    return [x for x in base if x != id_]


def pick_default() -> None:
    return None


def pick_recalibrate(rows: List[BatchRow]) -> List[int]:
    return [r.a["id"] for r in batch_calibratable(rows)]


def pick_clear() -> List[int]:
    return []


def pick_in_range(rows: List[BatchRow]) -> List[int]:
    return [r.a["id"] for r in batch_calibratable(rows) if r.status == "ok"]


def calibration_model_string(source: str, fit: Optional[LagFit], d_lag: Optional[float]) -> Optional[str]:
    if source == "direct":
        return serialize_direct(d_lag) if d_lag is not None else None
    return serialize_fit(fit) if fit else None


_COPIED = ["model_name", "test_date", "test_time", "temperature_c", "power_source_device",
           "power_response_device", "gas_atmosphere", "wave_type", "analysis_mode", "r1_mm", "r2_mm",
           "amplitude_a1", "amplitude_a2", "period_t", "frequency_f", "period_t_resp", "frequency_f_resp",
           "angular_freq_w", "raw_lag_dt", "raw_phase_phi", "ln_term", "alpha_combined_raw",
           "alpha_phase_raw"]


def build_calibrated_row(src: dict, lag: float, result: AppliedLag, graph_image: Optional[str],
                         ref_ids: List[int], model: Optional[str]) -> dict:
    row = {k: src.get(k) for k in _COPIED}
    row.update({
        "graph_image": graph_image or None,     # "" (no stored graph) and None (fetch failed) both insert null
        "use_calibration": True,
        "system_lag": lag,
        "net_lag_dt": result.net_lag_dt,
        "net_phase_phi": result.net_phase_phi,
        "alpha_combined_cal": result.alpha_combined_cal,
        "alpha_phase_cal": result.alpha_phase_cal,
        "is_reference": False,
        "calibrated_from_id": src["id"],
        "calibration_ref_ids": ",".join(str(i) for i in ref_ids),
        "calibration_model": model,
    })
    return row


def mark_report(done: int, total: int, failures: List[str]) -> str:
    return f"Marked as reference: {done}/{total}" + (f" · {'; '.join(failures)}" if failures else "")


def batch_report(written: int, n_ok: int, n_rows: int, n_calibratable: int, had_copies: int,
                 failures: List[str]) -> str:
    skipped = n_rows - n_ok
    not_cal = n_rows - n_calibratable
    s = f"Saved {written}/{n_ok}"
    if skipped > 0:
        s += f" · {skipped} skipped (not calibratable)"
        if not_cal > 0:
            s += f" · {not_cal} not calibratable"
        if had_copies > 0:
            s += f" · {had_copies} already calibrated"
    if failures:
        s += f" · {'; '.join(failures)}"
    return s
