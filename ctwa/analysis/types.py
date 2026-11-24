"""Shared types of the analysis port.

Each dataclass mirrors a TypeScript interface of the webapp; the Python field
name is the camelCase name with "_" before each capital, lower-cased
(amplitudeA1 -> amplitude_a1). Fields that are optional or `| null` in the
TypeScript default to None and come after the required ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class AnalysisParams:  # lib/analysis.ts
    model_name: str
    test_date: str
    test_time: str
    t_cal: str  # C80 start time HH:MM:SS
    t_src: str  # Keithley start time HH:MM:SS
    r1_mm: float
    r2_mm: float
    c80_time_unit: str  # 'Seconds' | 'Minutes' | 'Hours' | 'ms'
    c80_pwr_unit: str  # 'mW' | 'Watts' | 'uW'
    src_time_unit: str
    src_pwr_unit: str
    use_calibration: bool
    system_lag: float
    analysis_mode: str  # 'Auto' | 'AutoHybrid' | 'AutoFFT' | 'AutoFit' | 'Manual'
    fft_period_override: Optional[float] = None
    cycle_shift: Optional[float] = None
    day_offset: Optional[float] = None
    clock_ahead_s: Optional[float] = None
    manual_snap: Optional[bool] = None


@dataclass
class AnalysisResults:  # lib/analysis.ts
    amplitude_a1: float
    amplitude_a2: float
    period_t: float
    frequency_f: float
    angular_freq_w: float
    raw_lag_dt: float
    raw_phase_phi: float
    ln_term: float
    alpha_phase_raw: float
    alpha_phase_cal: float
    net_lag_dt: float
    net_phase_phi: float
    t_min: float
    t_max: float
    marker_src_time: float
    marker_src2_time: float
    marker_cal_time: float
    mean_peak_src: float
    mean_trough_src: float
    mean_peak_cal: float
    mean_trough_cal: float
    period_t_resp: Optional[float] = None
    frequency_f_resp: Optional[float] = None
    alpha_combined_raw: Optional[float] = None
    alpha_combined_cal: Optional[float] = None
    lag_se: Optional[float] = None
    lag_se_source: Optional[str] = None  # 'blocks' | 'formal' | 'pairs'
    lag_blocks: Optional[int] = None
    lag_cycles: Optional[int] = None
    lag_near_edge: Optional[bool] = None


@dataclass
class SyncedData:  # lib/analysis.ts
    t_src: List[float]
    v_src: List[float]
    t_cal: List[float]
    v_cal: List[float]


@dataclass
class CombinedParsed:  # lib/fileParser.ts
    time: List[float]  # seconds
    source: List[float]  # SMU source power, mW
    response: List[float]  # HeatFlow DC response, mW
    temperature: List[float]  # sample temperature, deg C (NaN where absent)


@dataclass
class SineFit:  # lib/sineFit.ts
    amplitude: float
    phase: float
    sigma: float
    se_phase: float
    n: int


@dataclass
class SineLag:  # lib/sineFit.ts
    lag: float
    se_source: str  # 'blocks' | 'formal'
    blocks: int
    amplitude_src: float
    amplitude_cal: float
    phase_src: float
    lag_se: Optional[float] = None  # None when it could not be estimated


@dataclass
class LagChoice:  # lib/sineFit.ts
    dt: float
    cycles: int
    near_edge: bool


@dataclass
class LagPoint:  # lib/lagFit.ts
    period: float
    lag: float


@dataclass
class LagFit:  # lib/lagFit.ts
    kind: str  # 'sqrt' | 'linear' | 'power' | 'physical'
    params: List[float]
    label: str
    rms: float
    r2: float
    n: int
    p_min: float
    p_max: float
    predict: Callable[[float], float]


@dataclass
class PipelineOptions:  # lib/pipeline.ts
    wave_type: str  # 'sine' | 'square'
    smooth_to_sine: bool
    sel_min: float
    sel_max: float
    params: AnalysisParams
    square_period: Optional[float] = None
    clicks: Optional[List[Tuple[float, float]]] = None


class PipelineError(Exception):
    """code: 'tooFewPoints' | 'smoothFailed' | 'parseFailed' | 'notEnoughOverlap'."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
