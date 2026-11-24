"""Peak detection for thermal wave signals.

Literal port of lib/peakDetection.ts of the webapp.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import List, Tuple

from ctwa.analysis.jsmath import array_max, array_min, js_floor


def find_peaks(values: List[float], distance: float) -> List[int]:
    """Local maxima at least `distance` samples apart, in ascending index order."""
    n = len(values)
    if n < 3:
        return []

    candidates: List[int] = []
    for i in range(1, n - 1):
        if values[i] > values[i - 1] and values[i] >= values[i + 1]:
            candidates.append(i)

    if len(candidates) == 0:
        return []
    if distance <= 1:
        return candidates

    # Array.sort is stable; the comparator is values[b] - values[a] (descending).
    def cmp(a: int, b: int) -> float:
        return values[b] - values[a]

    ordered = sorted(candidates, key=cmp_to_key(cmp))
    keep = set()
    suppressed = set()

    for idx in ordered:
        if idx in suppressed:
            continue
        keep.add(idx)
        for other in ordered:
            if other != idx and abs(other - idx) < distance:
                suppressed.add(other)

    return [i for i in candidates if i in keep]


def auto_detect_peaks(
    time: List[float], values: List[float], min_distance_fraction: float = 0.05
) -> Tuple[List[int], List[float]]:
    distance = max(js_floor(len(values) * min_distance_fraction), 10)
    indices = find_peaks(values, distance)
    times = [time[i] for i in indices]
    return indices, times


def find_troughs(values: List[float], distance: float) -> List[int]:
    return find_peaks([-v for v in values], distance)


def compute_cycle_amplitude(values: List[float], peak_indices: List[int]) -> float:
    if len(peak_indices) < 2:
        return (array_max(values) - array_min(values)) / 2

    amplitudes: List[float] = []
    for k in range(len(peak_indices) - 1):
        p1 = peak_indices[k]
        p2 = peak_indices[k + 1]

        trough_val = values[p1]
        for i in range(p1 + 1, p2):
            if values[i] < trough_val:
                trough_val = values[i]

        peak_avg = (values[p1] + values[p2]) / 2
        amplitudes.append((peak_avg - trough_val) / 2)

    if len(amplitudes) == 0:
        return (array_max(values) - array_min(values)) / 2

    amplitudes.sort(key=cmp_to_key(lambda a, b: a - b))
    mid = len(amplitudes) // 2
    if len(amplitudes) % 2 == 1:
        return amplitudes[mid]
    return (amplitudes[mid - 1] + amplitudes[mid]) / 2


def snap_to_peak(
    click_time: float, time: List[float], values: List[float], window_samples: int = 50
) -> Tuple[float, float, int]:
    """Returns (time, value, index) of the highest sample near the click."""
    closest_idx = 0
    closest_dist = math.inf
    for i in range(len(time)):
        d = abs(time[i] - click_time)
        if d < closest_dist:
            closest_dist = d
            closest_idx = i

    start = max(0, closest_idx - window_samples)
    end = min(len(values), closest_idx + window_samples)

    max_idx = start
    for i in range(start, end):
        if values[i] > values[max_idx]:
            max_idx = i

    return time[max_idx], values[max_idx], max_idx
