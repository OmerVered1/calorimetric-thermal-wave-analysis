"""Column lists and metadata for the ``analyses`` table (lib/analysisColumns.ts, Summary page)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

__all__ = ["LIST_COLUMNS", "COLUMNS", "ColumnInfo"]

# Every column except the heavy blobs (graph_image, graph_json, extra_data): a select('*') over all
# rows exceeds the statement timeout, so listings use this and fetch plots per row.
LIST_COLUMNS: Tuple[str, ...] = (
    "id", "created_at", "model_name", "test_date", "test_time",
    "c80_filename", "keithley_filename", "r1_mm", "r2_mm", "t_cal", "t_src",
    "c80_time_unit", "c80_pwr_unit", "src_time_unit", "src_pwr_unit",
    "analysis_mode", "use_calibration", "system_lag", "t_min", "t_max",
    "amplitude_a1", "amplitude_a2", "period_t", "frequency_f", "angular_freq_w",
    "raw_lag_dt", "raw_phase_phi", "ln_term",
    "alpha_combined_raw", "alpha_combined_cal", "alpha_phase_raw", "alpha_phase_cal",
    "net_lag_dt", "net_phase_phi", "temperature_c",
    "power_source_device", "power_response_device", "wave_type",
    "period_t_resp", "frequency_f_resp", "gas_atmosphere",
    "is_reference", "reference_alpha_mm2s",
    "calibrated_from_id", "calibration_ref_ids", "calibration_model",
)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    label: str      # the webapp's Summary header (units included, e.g. "T (°C)")
    unit: str       # "" when the column has none; alphas are shown in mm²/s (stored in m²/s)
    numeric: bool   # right-aligned, compared as a number (False: text, a date or a flag)
    editable: bool  # Summary lets the user edit it


# (name, label, unit, numeric, editable). The first 27 are DISPLAY_COLS of app/summary/page.tsx in
# its order (numeric = not in its TEXT_KEYS); the rest are the other list columns, not editable there.
_ROWS = (
    ("id", "ID", "", True, False),
    ("model_name", "Model", "", False, True),
    ("test_date", "Date", "", False, True),
    ("temperature_c", "T (°C)", "°C", True, True),
    ("gas_atmosphere", "Atmosphere", "", False, True),
    ("analysis_mode", "Mode", "", False, True),
    ("r1_mm", "r₁ (mm)", "mm", True, True),
    ("r2_mm", "r₂ (mm)", "mm", True, True),
    ("amplitude_a1", "A₁ (mW)", "mW", True, True),
    ("amplitude_a2", "A₂ (mW)", "mW", True, True),
    ("period_t", "Src Period (s)", "s", True, True),
    ("period_t_resp", "Resp Period (s)", "s", True, True),
    ("frequency_f", "Src f (Hz)", "Hz", True, True),
    ("frequency_f_resp", "Resp f (Hz)", "Hz", True, True),
    ("angular_freq_w", "ω (rad/s)", "rad/s", True, True),
    ("raw_lag_dt", "Δt (s)", "s", True, True),
    ("raw_phase_phi", "φ (rad)", "rad", True, True),
    ("ln_term", "ln term", "", True, True),
    ("alpha_combined_raw", "α comb (raw)", "mm²/s", True, True),
    ("alpha_phase_raw", "α phase (raw)", "mm²/s", True, True),
    ("use_calibration", "Cal", "", False, True),
    ("system_lag", "Lag (s)", "s", True, True),
    ("calibration_model", "Cal source", "", False, False),
    ("calibration_ref_ids", "Refs", "", False, False),
    ("net_lag_dt", "Net Δt (s)", "s", True, True),
    ("alpha_combined_cal", "α comb (cal)", "mm²/s", True, True),
    ("alpha_phase_cal", "α phase (cal)", "mm²/s", True, True),
    # list columns the Summary table does not show
    ("created_at", "Created", "", False, False),
    ("test_time", "Time", "", False, False),
    ("c80_filename", "C80 file", "", False, False),
    ("keithley_filename", "Keithley file", "", False, False),
    ("t_cal", "T cal", "", False, False),
    ("t_src", "T src", "", False, False),
    ("c80_time_unit", "C80 time unit", "", False, False),
    ("c80_pwr_unit", "C80 power unit", "", False, False),
    ("src_time_unit", "Src time unit", "", False, False),
    ("src_pwr_unit", "Src power unit", "", False, False),
    ("t_min", "t min (s)", "s", True, False),
    ("t_max", "t max (s)", "s", True, False),
    ("net_phase_phi", "Net φ (rad)", "rad", True, False),
    ("power_source_device", "Power source", "", False, False),
    ("power_response_device", "Response device", "", False, False),
    ("wave_type", "Wave", "", False, False),
    ("is_reference", "Reference", "", False, False),
    ("reference_alpha_mm2s", "Ref α (mm²/s)", "mm²/s", True, False),
    ("calibrated_from_id", "Calibrated from", "", True, False),
)

COLUMNS: Dict[str, ColumnInfo] = {r[0]: ColumnInfo(*r) for r in _ROWS}

assert set(COLUMNS) == set(LIST_COLUMNS)
