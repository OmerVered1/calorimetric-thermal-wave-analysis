"""Screenshots of the Statistics tab in the main window (only when CTWA_SHOT_DIR is set)."""
from __future__ import annotations

import json
import os
import random

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SHOT_DIR = os.environ.get("CTWA_SHOT_DIR")
pytestmark = pytest.mark.skipif(not SHOT_DIR, reason="CTWA_SHOT_DIR not set")

FIX = os.path.join(os.path.dirname(__file__), "data", "stats_rows.json")


def _rows():
    with open(FIX, encoding="utf-8") as f:
        base = json.load(f)
    rng = random.Random(3)
    out = list(base)
    for i in range(60):
        r = dict(base[i % len(base)])
        r["id"] = 100 + i
        r["calibrated_from_id"] = None
        r["period_t"] = rng.choice([75, 150, 300, 600, 1200, 2400])
        r["period_t_resp"] = r["period_t"] * 1.01
        r["frequency_f"] = 1 / r["period_t"]
        for k in ("alpha_combined_raw", "alpha_phase_raw", "alpha_combined_cal", "alpha_phase_cal", "raw_lag_dt",
                  "raw_phase_phi", "ln_term", "amplitude_a1", "amplitude_a2"):
            if r.get(k):
                r[k] = r[k] * rng.uniform(0.85, 1.15)
        out.append(r)
    return out


def test_screenshots(tmp_path):
    from PySide6.QtWidgets import QApplication
    from ctwa import app as appmod
    from ctwa.stats.view_state import ViewState
    app = QApplication.instance() or QApplication([])
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.resize(1500, 1000)
    w.show()
    w.tabs.setCurrentWidget(w.statistics_tab)
    tab = w.statistics_tab
    rows = _rows()
    presets = []

    def shot(name, view, section):
        tab._view = view
        tab.controls.set_view(view)
        tab.set_rows(rows, presets)
        app.processEvents()
        tab.scroll_to(section)
        app.processEvents()
        w.grab().save(os.path.join(SHOT_DIR, "app_stats_%s.png" % name))
        tab.scroll.widget().grab().save(os.path.join(SHOT_DIR, "statistics_%s.png" % name))

    shot("box", ViewState(chart_type="box"), "builder")
    shot("violin", ViewState(chart_type="violin"), "builder")
    shot("scatter_trend", ViewState(chart_type="scatter", color_by="Model", y_metric="raw_phase_phi"), "builder")
    shot("alpha_period", ViewState(alpha_series=["combined_raw", "phase_raw"]), "alpha")
    shot("heatmap", ViewState(), "corr")
    w.close()

