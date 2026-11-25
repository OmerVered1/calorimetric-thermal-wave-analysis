"""History tab (Results tab, Task 9), offscreen with a FakeLoader."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from ctwa.ui.results.history_tab import HistoryTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Stainless Steel", "test_date": "%02d/11/2026" % i, "temperature_c": 700 + i,
         "analysis_mode": "Auto", "gas_atmosphere": "Ar", "period_t": 600.4, "raw_lag_dt": 105.2,
         "use_calibration": False, "r1_mm": 6.72, "r2_mm": 14.86,
         "alpha_combined_raw": 8.2e-6, "alpha_phase_raw": 8.5123e-6, "alpha_combined_cal": None,
         "alpha_phase_cal": None, "ln_term": 0.5, "amplitude_a1": 12.3, "amplitude_a2": 5.7}
    r.update(kw)
    return r


ROWS = [row(1, model_name="Alumina", temperature_c=None),
        row(2, use_calibration=True, system_lag=12, net_lag_dt=93.2, alpha_combined_cal=7e-6,
            alpha_phase_cal=7.5e-6, calibration_ref_ids="5,6", calibration_model="linear:1,2",
            calibrated_from_id=2),
        row(3, is_reference=True, reference_alpha_mm2s=4.123456, model_name="Copper steel")]
FIG = json.dumps({"data": [{"x": [0, 1, 2], "y": [1, 2, 3], "name": "Source", "type": "scatter"}], "layout": {}})


@pytest.fixture
def make(qapp):
    made = []

    def _make(rows=ROWS, **kw):
        loader = FakeLoader(rows)
        tab = HistoryTab(loader, **kw)
        tab.resize(1200, 700)
        tab.show()
        made.append(tab)
        return tab, loader
    yield _make
    for t in made:
        t.close()


def table_ids(tab):
    return [tab.table.item(r, 0).data(Qt.UserRole) for r in range(tab.table.rowCount())]


def graph_requests(loader):
    return [c[1] for c in loader.calls if c[0] == "request_graph"]


def test_columns_cells_and_title(make):
    tab, _ = make()
    t = tab.table
    assert [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())] == [
        "ID", "Model", "Date", "Mode", "r₁", "r₂", "α comb (raw)", "α phase (raw)", "Cal", "T (°C)"]
    assert table_ids(tab) == [3, 2, 1]                      # newest date first
    cells = {c: t.item(2, c).text() for c in range(10)}    # row 2 = id 1
    assert cells[0] == "1" and cells[4] == "6.72" and cells[5] == "14.86"
    assert cells[7] == "8.512" and cells[8] == "✗" and cells[9] == "—"
    assert t.item(1, 8).text() == "✓"
    assert tab.title_text() == "All Analyses (3 total)"
    tab.set_search("steel")
    assert tab.title_text() == "All Analyses (2 / 3 total)"
    assert table_ids(tab) == [3, 2]


def test_search_uses_only_history_fields(make):
    tab, _ = make()
    tab.set_search("Ar")                 # gas is not searched; "Ar" is in no other field
    assert table_ids(tab) == []
    tab.set_search("#702")
    assert table_ids(tab) == [2]
    tab.set_search("no such run")
    assert table_ids(tab) == []
    assert tab.table.rowCount() == 0


def test_first_row_selected_and_detail(make):
    tab, loader = make()
    assert tab.selected_id() == 3
    assert graph_requests(loader) == [3]
    assert tab.figure_view().mode() == "loading"
    tab.select_id(2)
    assert tab.kpis() == ["7.500", "7.000", "600.4", "105.2"]
    d = tab.detail_text()
    assert d["Radii"] == "r₁=6.72mm, r₂=14.86mm"
    assert d["System Lag"] == "12.0s" and d["Net Δt"] == "93.20s"
    assert d["α Phase (cal)"] == "7.500 mm²/s"
    assert d["Calibrated via"].startswith("2 references · ")
    assert d["reference(s)"] == "#5, #6" and d["Copy of run"] == "#2"
    assert d["Device-lag curve lag(P)"] == "linear:1,2"
    assert d["Source Period T"] == "600.40s" and d["Source Frequency"] == "—Hz"   # the page appends the unit to the dash too
    assert tab.header_line() == "02/11/2026 · Auto · Cal (Lag: 12s)"
    tab.select_id(1)
    assert tab.kpis() == ["8.512", "8.200", "600.4", "105.2"]
    d = tab.detail_text()
    assert d["Temperature"] == "25°C" and "System Lag" not in d and "Known α (mm²/s)" not in d
    assert tab.header_line() == "01/11/2026 · Auto · No Cal"
    tab.select_id(3)
    assert tab.detail_text()["Known α (mm²/s)"] == "4.123 mm²/s"


def test_combo_lists_all_rows_even_when_hidden(make):
    tab, _ = make()
    tab.set_search("alumina")
    assert table_ids(tab) == [1]
    assert tab.combo.count() == 3
    assert tab.combo.itemText(2).startswith("Alumina | 01/11/2026 | Auto | No Cal")
    assert "Cal (Lag: 12s)" in tab.combo.itemText(1)
    tab.combo.setCurrentIndex(1)
    assert tab.selected_id() == 2


def test_arrow_keys_follow_sorted_order(make):
    tab, _ = make()
    tab.table.setFocus()
    assert tab.selected_id() == 3
    QTest.keyClick(tab.table, Qt.Key_Down)
    assert tab.selected_id() == 2
    QTest.keyClick(tab.table, Qt.Key_Down)
    QTest.keyClick(tab.table, Qt.Key_Down)
    assert tab.selected_id() == 1          # stays at the last row
    QTest.keyClick(tab.table, Qt.Key_Up)
    assert tab.selected_id() == 2
    tab.header_click("id")                 # ascending
    assert table_ids(tab) == [1, 2, 3]
    QTest.keyClick(tab.table, Qt.Key_Down)
    assert tab.selected_id() == 3


def test_three_state_sort(make):
    tab, _ = make()
    tab.header_click("id")
    assert table_ids(tab) == [1, 2, 3]
    tab.header_click("id")
    assert table_ids(tab) == [3, 2, 1]
    tab.header_click("id")
    assert table_ids(tab) == [3, 2, 1] and tab.sort_state() == (None, None)


def test_request_graph_once_per_change(make):
    tab, loader = make()
    tab.select_id(3)                       # unchanged: nothing new
    tab.select_id(2)
    tab.select_id(1)
    assert graph_requests(loader) == [3, 2, 1]


def test_late_graph_for_other_row_is_ignored(make):          # Review Focus 1
    tab, loader = make()
    tab.select_id(1)                       # A = 3 was requested first
    loader.graph_loaded.emit(3, FIG)
    assert tab.figure_view().mode() == "loading"
    assert tab.kpis()[0] == "8.512"        # row 1's numbers
    loader.graph_loaded.emit(1, FIG)
    assert tab.figure_view().mode() == "figure"
    tab.select_id(2)
    loader.graph_loaded.emit(2, None)
    assert tab.figure_view().mode() == "bars"


def test_broken_figure_falls_back(make):                       # Review Focus 5
    tab, loader = make()
    loader.graph_loaded.emit(3, "<broken json")
    assert tab.figure_view().mode() == "bars"
    loader.graph_loaded.emit(3, "{}")
    assert tab.figure_view().mode() in ("bars", "empty")


def test_open_in_viewer(make):
    tab, _ = make()
    got = []
    tab.open_in_viewer.connect(got.append)
    tab.select_id(2)
    tab.open_button.click()
    assert got == [2]


def test_rows_changed_keeps_or_moves_selection(make):
    tab, loader = make()
    tab.select_id(2)
    n = len(graph_requests(loader))
    loader.set_rows(ROWS)
    assert tab.selected_id() == 2 and len(graph_requests(loader)) == n
    loader.set_rows([r for r in ROWS if r["id"] != 2])        # gone: the next row in order
    assert tab.selected_id() == 1
    loader.set_rows([r for r in ROWS if r["id"] == 3])
    assert tab.selected_id() == 3


def test_no_rows_shows_no_data(make):
    tab, loader = make(rows=[])
    assert tab.selected_id() is None
    assert tab.message_text() == "Loading…"
    loader.set_rows([])
    assert tab.message_text() == "No data"
    loader.set_rows(ROWS)
    assert tab.selected_id() == 3 and tab.message_text() == ""


def test_select_id_before_rows_arrive(make):
    tab, loader = make(rows=[])
    tab.select_id(2)
    loader.set_rows(ROWS)
    assert tab.selected_id() == 2


def test_no_attribute_hides_a_qwidget_member(make):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    tab, _ = make()
    assert [n for n in vars(tab) if hasattr(QWidget, n) and not isinstance(getattr(QWidget, n), Signal)] == []


def test_visible_table_fill_is_fast(make):
    """A refresh of a shown 300-row table must not re-measure every row per cell (was 5.5 s at 100 rows)."""
    import time
    rows = [row(i, model_name="Model %d" % i) for i in range(1, 301)]
    tab, loader = make(rows)
    assert tab.table.isVisible() and tab.table.rowCount() == 300
    t0 = time.perf_counter()
    loader.set_rows([dict(r, temperature_c=800) for r in rows])
    tab.set_search("Model 1")
    tab.set_search("")
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, "3 refreshes of 300 rows took %.2f s" % elapsed


def test_failed_graph_shows_note_and_bars(make):
    tab, loader = make()
    tab.select_id(2)
    assert tab.figure_view().mode() == "loading"
    loader.graph_loaded.emit(2, None)
    fv = tab.figure_view()
    assert fv.mode() != "loading"
    assert fv.note() == "Could not load the graph"
    assert fv.bar_labels()
    loader.graph_loaded.emit(1, None)           # not the selected one: ignored
    assert fv.note() == "Could not load the graph"


def test_read_error_banner_with_rows_on_screen(make):
    tab, loader = make()
    loader.failed.emit("net", "no route")
    assert tab.banner_label.isVisible()
    assert tab.banner_label.text() == "Can't reach the database: no route"
    assert tab.table.rowCount() == 3
    loader.set_rows(ROWS)
    assert not tab.banner_label.isVisible()


def test_created_is_local_time_and_parses_fractions(monkeypatch):
    import time
    from ctwa.ui.results.history_tab import _created
    monkeypatch.setenv("TZ", "Asia/Jerusalem")
    time.tzset()
    try:
        assert _created("2026-11-20T10:00:00Z") == "11/20/2026, 12:00:00 PM"
        assert _created("2026-11-20T10:00:00.5Z") == "11/20/2026, 12:00:00 PM"
        assert _created("2026-11-20T10:00:00.123456789+00:00") == "11/20/2026, 12:00:00 PM"
        assert _created("2026-11-20T10:00:00.12Z") == "11/20/2026, 12:00:00 PM"
    finally:
        monkeypatch.undo()
        time.tzset()
