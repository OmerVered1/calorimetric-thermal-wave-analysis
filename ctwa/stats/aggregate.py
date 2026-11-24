"""Statistics aggregation: means, bins, pairs, theory grids, correlation, summary (literal ports of page.tsx)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ctwa.analysis.diffusivity import theoretical_lag_dt, theoretical_phase
from ctwa.analysis.jsmath import js_round, js_to_precision
from ctwa.stats.model import extract_y, get_period

__all__ = ["mean", "std_pop", "std_sample", "linear_fit", "PeriodBin", "bin_by_period", "pair_segments", "common_dr",
           "distinct_dr", "log_grid", "theory_curve", "CORR_LABELS", "corr_matrix", "points_in_polygon", "SummaryRow",
           "STAT_KEYS", "summary_rows", "fmt_stat", "summary_csv"]


def mean(v: Sequence[float]) -> float:
    s = 0.0
    for x in v:
        s += x
    return s / len(v)


def std_pop(v: Sequence[float]) -> float:
    """Divide by n (the page's std(): bar error bars and the summary)."""
    m = mean(v)
    s = 0.0
    for x in v:
        s += (x - m) ** 2
    return math.sqrt(s / len(v))


def std_sample(v: Sequence[float]) -> float:
    """n - 1; a single value has none (the α mean ± std overlay)."""
    if len(v) < 2:
        return 0
    m = mean(v)
    s = 0.0
    for x in v:
        s += (x - m) ** 2
    return math.sqrt(s / (len(v) - 1))


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> Optional[Tuple[float, float]]:
    """(slope, intercept) by the normal equations, as page.tsx linearFit; needs n >= 3."""
    n = len(xs)
    if n < 3:
        return None
    sx = sy = sxx = sxy = 0.0
    for i in range(n):
        sx += xs[i]
        sy += ys[i]
    for i in range(n):
        sxx += xs[i] * xs[i]
    for i in range(n):
        sxy += xs[i] * ys[i]
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return ((n * sxy - sx * sy) / denom, (sy * sxx - sx * sxy) / denom)


@dataclass(frozen=True)
class PeriodBin:
    x: float
    y: float
    sd: float
    n: int


def bin_by_period(points: Iterable[Tuple[float, float]]) -> List[PeriodBin]:
    """Runs whose periods agree within 4 % count as one period (a new bin starts at x > first_x * 1.04)."""
    pts = sorted(points, key=lambda p: p[0])
    groups: List[List[Tuple[float, float]]] = []
    for p in pts:
        if groups and p[0] <= groups[-1][0][0] * 1.04:
            groups[-1].append(p)
        else:
            groups.append([p])
    out = []
    for g in groups:
        ys = [p[1] for p in g]
        out.append(PeriodBin(mean([p[0] for p in g]), mean(ys), std_sample(ys), len(ys)))
    return out


Segment = Tuple[Tuple[float, float], Tuple[float, float]]


def pair_segments(rows: Iterable[Dict[str, Any]], model: str, source: str, phase: bool, combined: bool) -> List[Segment]:
    """One segment per run, from its raw alpha to its calibrated one at the run's period (phase kind first)."""
    subset = [a for a in rows if a.get("model_name") == model]
    out: List[Segment] = []
    for on, raw_key, cal_key in ((phase, "alpha_phase_raw", "alpha_phase_cal"),
                                 (combined, "alpha_combined_raw", "alpha_combined_cal")):
        if not on:
            continue
        for a in subset:
            p = get_period(a, source)
            raw = extract_y(a, raw_key)
            cal = extract_y(a, cal_key)
            if p is None or raw is None or cal is None:
                continue
            out.append(((p, raw), (p, cal)))
    return out


def distinct_dr(rows: Iterable[Dict[str, Any]]) -> List[float]:
    """The distinct dr = r2 - r1 (mm, 3 dp, > 0), most common first (ties keep first appearance)."""
    counts: Dict[float, int] = {}
    for a in rows:
        r1, r2 = a.get("r1_mm"), a.get("r2_mm")
        if r1 is None or r2 is None:
            continue
        dr = js_round((r2 - r1) * 1000) / 1000
        if not dr > 0:
            continue
        counts[dr] = counts.get(dr, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def common_dr(rows: Iterable[Dict[str, Any]]) -> Optional[float]:
    d = distinct_dr(rows)
    return d[0] if d else None


def log_grid(xmin: float, xmax: float, n: int = 160) -> List[float]:
    return [xmin * (xmax / xmin) ** (k / (n - 1)) for k in range(n)]


_THEORY_X = ("Period (s)", "Frequency (Hz)")


def theory_curve(alpha_mm2s: float, dr_mm: float, xs: Iterable[float], x_axis: str, kind: str) -> List[Optional[float]]:
    """theoretical phase / lag at each x (a period, or a frequency whose period is 1/x); None where undefined."""
    predict = theoretical_phase if kind == "phase" else theoretical_lag_dt
    out: List[Optional[float]] = []
    for x in xs:
        if x_axis not in _THEORY_X or not x > 0:
            out.append(None)
            continue
        out.append(predict(alpha_mm2s, dr_mm, x if x_axis == "Period (s)" else 1 / x))
    return out


CORR_LABELS: Tuple[str, ...] = ("A₁", "A₂", "A₁/A₂", "Period", "Δt", "φ", "ln term", "α comb raw", "α phase raw",
                                "T (°C)")
_CORR_KEYS = ("amplitude_a1", "amplitude_a2", "a1_a2_ratio", "period_t", "raw_lag_dt", "raw_phase_phi", "ln_term",
              "alpha_combined_raw", "alpha_phase_raw", "temperature_c")


def corr_matrix(rows: Iterable[Dict[str, Any]], source: str = "src") -> List[List[float]]:
    rows = list(rows)
    vectors = [[extract_y(a, k, source) for a in rows] for k in _CORR_KEYS]
    n = len(vectors)
    matrix: List[List[float]] = []
    for i in range(n):
        line: List[float] = []
        for j in range(n):
            xs: List[float] = []
            ys: List[float] = []
            for k in range(len(rows)):
                a, b = vectors[i][k], vectors[j][k]
                if a is not None and b is not None:
                    xs.append(a)
                    ys.append(b)
            if len(xs) < 3:
                line.append(0.0)
                continue
            mx, my = mean(xs), mean(ys)
            num = sxx = syy = 0.0
            for idx in range(len(xs)):
                num += (xs[idx] - mx) * (ys[idx] - my)
            for x in xs:
                sxx += (x - mx) ** 2
            for y in ys:
                syy += (y - my) ** 2
            dx, dy = math.sqrt(sxx), math.sqrt(syy)
            line.append(0.0 if dx * dy == 0 else num / (dx * dy))
        matrix.append(line)
    return matrix


def points_in_polygon(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> bool:
    """Even-odd rule."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


STAT_KEYS = ("combined_raw", "phase_raw", "combined_cal", "phase_cal")
_STAT_SRC = {"combined_raw": "alpha_combined_raw", "phase_raw": "alpha_phase_raw",
             "combined_cal": "alpha_combined_cal", "phase_cal": "alpha_phase_cal"}
Stat = Tuple[int, float, float, float, float]


@dataclass
class SummaryRow:
    model: str
    n: int
    stats: Dict[str, Optional[Stat]]     # (n, mean, std_pop, min, max); None when the series is empty


def summary_rows(rows: Iterable[Dict[str, Any]]) -> List[SummaryRow]:
    rows = list(rows)
    models: List[str] = []
    for a in rows:
        if a.get("model_name") not in models:
            models.append(a.get("model_name"))
    out: List[SummaryRow] = []
    for model in models:
        subset = [a for a in rows if a.get("model_name") == model]
        stats: Dict[str, Optional[Stat]] = {}
        for key in STAT_KEYS:
            vals = [v for v in (extract_y(a, _STAT_SRC[key]) for a in subset) if v is not None]
            if not vals:
                stats[key] = None
                continue
            lo, hi = math.inf, -math.inf
            for v in vals:
                if v < lo:
                    lo = v
                if v > hi:
                    hi = v
            stats[key] = (len(vals), mean(vals), std_pop(vals), lo, hi)
        out.append(SummaryRow(model, len(subset), stats))
    return out


def fmt_stat(x: Optional[float], digits: int) -> str:
    return "—" if x is None else js_to_precision(x, digits)


def summary_csv(rows: Iterable[Dict[str, Any]]) -> str:
    headers = ["Model", "N"]
    for key in ("comb_raw", "phase_raw", "comb_cal", "phase_cal"):
        headers += ["alpha_%s_%s" % (key, s) for s in ("mean", "std", "min", "max")]
    lines = [",".join(headers)]
    for s in summary_rows(rows):
        cells = [s.model, str(s.n)]
        for key in STAT_KEYS:
            st = s.stats[key]
            cells += [fmt_stat(st[1] if st else None, 4), fmt_stat(st[2] if st else None, 3),
                      fmt_stat(st[3] if st else None, 4), fmt_stat(st[4] if st else None, 4)]
        lines.append(",".join(cells))
    return "\n".join(lines)
