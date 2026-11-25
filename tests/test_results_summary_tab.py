"""Summary tab view (Results tab, Task 7), offscreen with a FakeLoader."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from results_fakes import FakeLoader  # noqa: E402
from ctwa.ui.results.summary_logic import (SUMMARY_COLS, csv_bytes, hidden_for_preset, summary_stats)  # noqa: E402
from ctwa.ui.results.summary_tab import SummaryTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Stainless Steel", "test_date": "%02d/11/2026" % i, "temperature_c": 700 + i,
         "analysis_mode": "Auto", "period_t": 100.0 * i, "use_calibration": False,
         "alpha_combined_raw": 8.5e-6, "alpha_phase_raw": 8.4e-6, "ln_term": 0.5, "raw_phase_phi": 0.2,
         "alpha_combined_cal": None}
    r.update(kw)
    return r


ROWS = [row(1), row(2, model_name="Alumina", use_calibration=True, alpha_combined_cal=7e-6,
                    analysis_mode="Manual", alpha_combined_raw=9e-6), row(3)]


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


@pytest.fixture
def make(qapp, settings):
    made = []

    def _make(rows=ROWS, loaded=True, st=None):
        loader = FakeLoader(rows if loaded else [])
        tab = SummaryTab(loader, st if st is not None else settings)
        tab.resize(1000, 600)
        tab.show()
        made.append(tab)
        return tab, loader
    yield _make
    for t in made:
        t.close()


def test_stats_and_search_caption(make):
    tab, _ = make()
    exp = summary_stats(tab.model.display_rows())
    assert tab.stat_texts() == {"Total Analyses": "3", "Unique Models": "2", "Avg α (raw)": exp["avg_raw"],
                                "Avg α (cal)": exp["avg_cal"]}
    assert tab.stat_texts()["Avg α (raw)"] == "8.667 mm²/s"
    assert tab.caption.text() == ""
    tab.search_edit.setText("steel")
    assert tab.stat_texts()["Total Analyses"] == "2" and tab.stat_texts()["Unique Models"] == "1"
    assert tab.caption.text() == "Statistics for the 2 analyses shown (of 3)."
    assert tab.shown_count() == 2
    assert tab.info_label.text().startswith("Showing 2 of 3 results · Double-click a cell to edit")


def test_presets_and_persistence(make, settings):
    tab, _ = make()
    tab._preset_buttons["key"].click()
    assert tab.hidden_keys() == set(hidden_for_preset("key"))
    keys = tab.visible_column_keys()
    assert "id" in keys and "model_name" in keys and "r1_mm" not in keys and "alpha_phase_raw" in keys
    assert tab._preset_buttons["key"].isChecked() and not tab._preset_buttons["all"].isChecked()
    tab._column_actions["temperature_c"].setChecked(False)
    assert not any(b.isChecked() for b in tab._preset_buttons.values())
    tab._preset_buttons["all"].click()
    assert len(tab.visible_column_keys()) == 27
    tab._column_actions["r1_mm"].setChecked(False)
    tab.density_button.click()
    assert tab.density() == "comfortable"
    assert tab.density_button.text() == "Compact rows"
    tab2, _ = make(st=QSettings(settings.fileName(), QSettings.IniFormat))
    assert tab2.hidden_keys() == {"r1_mm"} and tab2.density() == "comfortable"
    assert tab2.table.verticalHeader().defaultSectionSize() > tab.table.verticalHeader().minimumSectionSize()


def test_select_all_shown_and_compare(make):
    rows = [row(i) for i in range(1, 7)]
    tab, _ = make(rows)
    got = []
    tab.compare_requested.connect(got.append)
    tab.search_edit.setText("703")        # temperature of row 3
    assert tab.shown_count() == 1
    tab.select_all.click()
    assert tab.selected_ids() == [3]
    tab.search_edit.setText("")
    tab.select_all.click()                # not all shown selected -> select all shown
    assert len(tab.selected_ids()) == 6
    assert not tab.compare_button.isEnabled()
    assert tab.compare_button.toolTip() == "Compare up to 4 at a time"
    assert tab.sel_label.text() == "6 analyses selected" and not tab.sel_bar.isHidden()
    tab.model.set_selected(1, False)
    tab.model.set_selected(2, False)
    assert tab.compare_button.isEnabled()
    tab.compare_button.click()
    assert got == [[6, 5, 4, 3]]          # table order: newest first
    tab.sel_clear.click()
    assert tab.sel_bar.isHidden()


def test_export_csv(make, tmp_path):
    tab, _ = make()
    tab.search_edit.setText("steel")
    p = tmp_path / "a.csv"
    n = tab.export_csv(str(p))
    assert n == 2
    data = p.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    base = [r for r in tab.model.display_rows() if r["model_name"] == "Stainless Steel"]
    assert data == csv_bytes(base)
    assert [r["id"] for r in base] == [3, 1]                    # base order even when sorted
    tab._header_clicked(1 + [c.key for c in SUMMARY_COLS].index("period_t"))
    assert tab.proxy.shown_ids() == [1, 3]
    assert tab.export_csv(str(p)) == 2 and p.read_bytes() == csv_bytes(base)
    assert len(data.decode("utf-8-sig").split("\n")[0].split(",")) == 27
    tab.model.set_selected(2, True)
    q = tmp_path / "b.csv"
    assert tab.export_csv(str(q), selected_only=True) == 1
    assert q.read_bytes() == csv_bytes([r for r in tab.model.display_rows() if r["id"] == 2])


def test_id_filter_chip_and_search_prefill(make):
    tab, _ = make()
    tab.set_id_filter({1, 3})
    assert tab.chip.isVisible() and tab.chip_label.text() == "2 runs from a link"
    assert tab.shown_count() == 2
    tab.chip_clear.click()
    assert not tab.chip.isVisible() and tab.shown_count() == 3
    tab.set_search("steel")
    assert tab.search_edit.text() == "steel"


def test_failed_banner_and_retry(make):
    tab, loader = make()
    loader.failed.emit("offline", "no route")
    assert tab.banner.isVisible()
    assert tab.banner_label.text() == "Can't reach the database: no route"
    assert tab.shown_count() == 3
    tab.retry_button.click()
    assert loader.calls == [("refresh",)]
    loader.set_rows(ROWS)
    assert not tab.banner.isVisible()


def test_loading_and_no_data(make):
    tab, loader = make(loaded=False)
    assert tab.message_label.text() == "Loading…" and tab.message_label.isVisible()
    loader.set_rows(ROWS)
    assert tab.table.isVisible() and not tab.message_label.isVisible()
    tab.search_edit.setText("zzzz")
    assert tab.message_label.text() == "No data" and tab.message_label.isVisible()
    tab.search_edit.setText("")
    loader.set_rows([])
    assert tab.message_label.text() == "No data"


def test_frozen_columns_stay_while_scrolled(make):
    tab, _ = make([row(i) for i in range(1, 61)])
    t = tab.table
    tab._preset_buttons["all"].click()
    QApplication.processEvents()
    hb = t.horizontalScrollBar()
    assert hb.maximum() > 0
    hb.setValue(hb.maximum())
    QApplication.processEvents()
    fr = t.frozen
    assert fr.isVisible() and fr.geometry().left() <= t.frameWidth() + 1
    assert fr.width() == t.frozen_width()
    # the overlay shows check, ID and Model and does not move
    assert [c for c in range(fr.model().columnCount()) if not fr.isColumnHidden(c)] == [0, 1, 2]
    proxy_ix = t.model().index(0, 2)
    assert fr.visualRect(proxy_ix).left() >= 0 and fr.visualRect(proxy_ix).width() > 0
    # while the main view's first data column has scrolled out from under it
    assert t.visualRect(t.model().index(0, 3)).right() < t.frozen_width()
    # vertical scrolling is shared
    assert t.verticalScrollBar().maximum() > 0
    t.verticalScrollBar().setValue(120)
    assert fr.verticalScrollBar().value() == t.verticalScrollBar().value() == 120
    fr.verticalScrollBar().setValue(60)
    assert t.verticalScrollBar().value() == 60
