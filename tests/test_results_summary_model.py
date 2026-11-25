"""Summary table model and proxy (Results tab, Task 6)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.analysis.references import material_color  # noqa: E402
from ctwa.ui.results.summary_logic import SUMMARY_COLS  # noqa: E402
from ctwa.ui.results.summary_model import SummaryModel, SummaryProxy  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Stainless Steel", "test_date": "0%d/11/2026" % i, "temperature_c": 700 + i,
         "analysis_mode": "Auto", "period_t": 100.0 * i, "use_calibration": False, "alpha_combined_raw": 8.5123e-6,
         "alpha_phase_raw": 8.5123e-6, "ln_term": 0.5, "raw_phase_phi": 0.2}
    r.update(kw)
    return r


ROWS = [row(1, period_t=300.0), row(2, model_name="Alumina", use_calibration=True, period_t=None),
        row(3, period_t=100.0)]


def col(key):
    return 1 + [c.key for c in SUMMARY_COLS].index(key)


@pytest.fixture
def mp(qapp):
    m = SummaryModel()
    p = SummaryProxy()
    p.setSourceModel(m)
    m.set_rows(ROWS)
    return m, p


def ids(p):
    return p.shown_ids()


def test_columns_and_roles(mp):
    m, _ = mp
    assert m.columnCount() == 28 and m.rowCount() == 3
    i = m.index(m.row_of(1), col("alpha_phase_raw"))
    assert m.data(i, Qt.DisplayRole) == "8.512"
    assert m.data(i, Qt.EditRole) == 8.5123e-06
    assert m.data(m.index(0, col("temperature_c")), Qt.TextAlignmentRole) & Qt.AlignRight
    assert m.data(m.index(0, col("model_name")), Qt.TextAlignmentRole) & Qt.AlignLeft
    dec = m.data(m.index(0, col("model_name")), Qt.DecorationRole)
    assert isinstance(dec, QColor) and dec == QColor(material_color(m.data(m.index(0, col("model_name")))))
    assert m.headerData(col("temperature_c"), Qt.Horizontal) == "T (°C)"
    assert m.data(m.index(0, 0), Qt.CheckStateRole) == Qt.Unchecked


def test_base_order_is_date_descending(mp):
    _, p = mp
    assert ids(p) == [3, 2, 1]


def test_ln_fix_is_display_only(qapp):
    m = SummaryModel()
    m.set_rows([row(1, ln_term=1, amplitude_a1=1.0, amplitude_a2=2.0, r1_mm=5.0, r2_mm=10.0, alpha_combined_raw=3e-6)])
    i = m.index(0, col("alpha_combined_raw"))
    assert m.data(i, Qt.DisplayRole) == "—"
    assert m.data(i, Qt.EditRole) == 3e-6
    assert m.row_by_id(1)["alpha_combined_raw"] == 3e-6


def test_three_state_sort(mp):
    _, p = mp
    p.set_sort("period_t", "asc")
    assert ids(p) == [2, 3, 1]       # None counts as 0
    p.set_sort("period_t", "desc")
    assert ids(p) == [1, 3, 2]
    p.set_sort(None, None)
    assert ids(p) == [3, 2, 1]
    assert [r["id"] for r in p.shown_rows()] == [3, 2, 1]


def test_filters_keep_selection(mp):
    m, p = mp
    m.set_selected(1, True)
    p.set_filters(model="Stainless Steel", cal="Calibrated Only")
    assert ids(p) == []
    p.set_filters(model="Stainless Steel")
    assert ids(p) == [3, 1]
    assert m.selected_ids() == {1}
    p.set_filters(cal="Calibrated Only")
    assert ids(p) == [2] and m.selected_ids() == {1}
    p.set_all_shown(True)
    assert m.selected_ids() == {1, 2}
    p.set_filters(query="alumina")
    m.set_all_shown(False)
    assert m.selected_ids() == {1}
    p.set_filters(ids={1, 3})
    assert ids(p) == [3, 1]


def test_refresh_keeps_selection_of_existing_ids(mp):
    m, p = mp
    for i in (1, 2, 3):
        m.set_selected(i, True)
    m.set_rows([row(1), row(3, temperature_c=999)])
    assert m.selected_ids() == {1, 3}
    assert ids(p) == [3, 1]
    assert m.data(m.index(m.row_of(3), col("temperature_c")), Qt.EditRole) == 999


def test_refresh_same_ids_resorts(mp):
    m, p = mp
    p.set_sort("period_t", "asc")
    m.set_rows([row(1, period_t=1.0), row(2, period_t=500.0), row(3, period_t=100.0)])
    assert ids(p) == [1, 3, 2]


def test_pending_hide(mp):
    m, p = mp
    p.set_sort("period_t", "asc")
    m.pending_hide({2})
    assert ids(p) == [3, 1] and m.rowCount() == 3 and m.row_by_id(2) is not None
    m.pending_hide(set())
    assert ids(p) == [2, 3, 1]


def test_distinct_models(mp):
    m, p = mp
    assert m.distinct_models() == ["Alumina", "Stainless Steel"] == p.distinct_models()
    assert p.distinct_modes() == ["Auto"]


def test_check_state_sets_selection(mp):
    m, _ = mp
    assert m.setData(m.index(0, 0), Qt.Checked, Qt.CheckStateRole)
    assert m.selected_ids() == {m.index(0, 0).data(Qt.UserRole + 1)}
