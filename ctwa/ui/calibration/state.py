"""One shared state for the Calibration tab: the rows, the presets and every selection.

Inputs are `set_rows` / `set_presets` and the plain attributes below (each setter emits `changed`
when the value really changes). Everything derived (`references`, `fits`, `applied`, `batch_rows`
...) is computed lazily and cached until the next `changed`. No network, no widgets.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from ctwa.analysis.calibration import AppliedLag, apply_device_lag
from ctwa.analysis.calibration_batch import BatchRow, batch_rows, batch_targets
from ctwa.analysis.calibration_logic import (
    PickerRow, RefLag, active_fit, active_source, applied_lag, direct_lag, direct_mean_period,
    fit_points, picker_rows, ref_lags, selected_lags, split_rows)
from ctwa.analysis.jsmath import js_number_to_string
from ctwa.analysis.lag_fit import fit_lag_models
from ctwa.results.helpers import with_ln_validity

_DEFAULTS = {
    "method": "phase",
    "selected_ref_ids": [],
    "model_kind": None,
    "lag_source": None,
    "target_id": None,
    "ref_filter_material": "",
    "ref_filter_temp": "",
    "ref_near_only": False,
    "ref_near_pct": 50.0,
    "ref_sort": "period",
    "mark_alpha": "",
    "mark_ids": [],
    "mark_filter_material": "",
    "mark_filter_temp": "",
    "batch_material": "",
    "batch_temp": "",
    "batch_picked": None,
}

# changing the key on the left also does the action on the right
_RESETS = {
    "ref_filter_material": {"ref_filter_temp": ""},
    "mark_filter_material": {"mark_filter_temp": ""},
    "batch_material": {"batch_picked": None},
    "batch_temp": {"batch_picked": None},
}


def _attr(name: str):
    def get(self):
        return self._v[name]

    def set_(self, value):
        if isinstance(value, list):
            value = list(value)
        if self._v[name] == value and type(self._v[name]) is type(value):
            return
        self._v[name] = value
        for other, reset in _RESETS.get(name, {}).items():
            self._v[other] = reset
        self._touch()

    return property(get, set_)


def _derived(fn: Callable):
    name = fn.__name__

    def get(self):
        if name not in self._cache:
            self._cache[name] = fn(self)
        return self._cache[name]

    return property(get, doc=fn.__doc__)


class CalibrationState(QObject):
    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._v: Dict[str, object] = {k: (list(v) if isinstance(v, list) else v)
                                      for k, v in _DEFAULTS.items()}
        self._rows: List[dict] = []
        self._presets: List[dict] = []
        self._cache: Dict[str, object] = {}

    # ---- inputs ----
    method = _attr("method")
    selected_ref_ids = _attr("selected_ref_ids")
    model_kind = _attr("model_kind")
    lag_source = _attr("lag_source")
    target_id = _attr("target_id")
    ref_filter_material = _attr("ref_filter_material")
    ref_filter_temp = _attr("ref_filter_temp")
    ref_near_only = _attr("ref_near_only")
    ref_near_pct = _attr("ref_near_pct")
    ref_sort = _attr("ref_sort")
    mark_alpha = _attr("mark_alpha")
    mark_ids = _attr("mark_ids")
    mark_filter_material = _attr("mark_filter_material")
    mark_filter_temp = _attr("mark_filter_temp")
    batch_material = _attr("batch_material")
    batch_temp = _attr("batch_temp")
    batch_picked = _attr("batch_picked")

    def _touch(self) -> None:
        self._cache.clear()
        self.changed.emit()

    @property
    def rows(self) -> List[dict]:
        return self._rows

    @property
    def presets(self) -> List[dict]:
        return self._presets

    def set_presets(self, presets: List[dict]) -> None:
        self._presets = list(presets)
        self._touch()

    def set_rows(self, rows: List[dict]) -> None:
        """New rows from the loader. Every selection is pruned to what still exists (a reference
        unmarked, a run deleted elsewhere); the batch pick is reset when its candidates changed."""
        before = self._batch_signature()
        self._rows = [with_ln_validity(r) for r in rows]
        self._cache.clear()
        refs, non_refs, _copies = split_rows(self._rows)
        ref_ids = {r["id"] for r in refs}
        non_ref_ids = {r["id"] for r in non_refs}
        all_ids = {r["id"] for r in self._rows}
        v = self._v
        v["selected_ref_ids"] = [i for i in v["selected_ref_ids"] if i in ref_ids]
        v["mark_ids"] = [i for i in v["mark_ids"] if i in non_ref_ids]
        if v["target_id"] is not None and v["target_id"] not in all_ids:
            v["target_id"] = None
        if v["batch_picked"] is not None:
            after = self._batch_signature()
            if after != before:
                v["batch_picked"] = None
            else:
                v["batch_picked"] = [i for i in v["batch_picked"] if i in non_ref_ids]
        self._touch()

    def _batch_signature(self):
        """The batch candidates and which of them already have a copy."""
        _refs, non_refs, copies = split_rows(self._rows)
        cands = batch_targets(non_refs, self._v["batch_material"], self._v["batch_temp"])
        return [(a["id"], tuple(copies.get(a["id"], []))) for a in cands]

    def apply_preset(self, p: dict) -> None:
        """Click on a preset: fill the mark α and narrow the mark list to its material."""
        self._v["mark_alpha"] = js_number_to_string(p["alpha_mm2s"])
        self._v["mark_filter_material"] = p["material_name"]
        self._v["mark_filter_temp"] = ""
        self._touch()

    # ---- derived ----
    @_derived
    def _split(self):
        return split_rows(self._rows)

    @property
    def references(self) -> List[dict]:
        return self._split[0]

    @property
    def non_references(self) -> List[dict]:
        return self._split[1]

    @property
    def copies(self) -> Dict[int, List[int]]:
        return self._split[2]

    @_derived
    def ref_lags(self) -> List[RefLag]:
        return ref_lags(self.references, self.method)

    @_derived
    def selected(self) -> List[RefLag]:
        return selected_lags(self.ref_lags, self.selected_ref_ids)

    @_derived
    def fits(self):
        return fit_lag_models(fit_points(self.selected))

    @_derived
    def fit(self):
        return active_fit(self.fits, self.model_kind)

    @_derived
    def source(self) -> str:
        return active_source(self.lag_source, self.fit)

    @_derived
    def direct_lag(self) -> Optional[float]:
        return direct_lag(self.selected)

    @_derived
    def direct_mean_period(self) -> Optional[float]:
        return direct_mean_period(self.selected)

    @_derived
    def target(self) -> Optional[dict]:
        if self.target_id is None:
            return None
        for r in self._rows:
            if r["id"] == self.target_id:
                return r
        return None

    @_derived
    def applied(self):
        return applied_lag(self.target, self.source, self.fit, self.direct_lag, self.direct_mean_period)

    @_derived
    def calibrated(self) -> Optional[AppliedLag]:
        if self.target is None or self.applied is None:
            return None
        return apply_device_lag(self.target, self.applied.lag)

    @_derived
    def batch_rows(self) -> List[BatchRow]:
        cands = batch_targets(self.non_references, self.batch_material, self.batch_temp)
        return batch_rows(cands, self.source, self.fit, self.direct_lag, self.direct_mean_period,
                          self.copies)

    @_derived
    def picker(self) -> List[PickerRow]:
        return picker_rows(self.ref_lags, self.target, self.ref_filter_material, self.ref_filter_temp,
                           self.ref_near_only, self.ref_near_pct, self.ref_sort)
