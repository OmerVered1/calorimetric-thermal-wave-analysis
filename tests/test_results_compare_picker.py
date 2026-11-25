"""Compare run picker (Results tab, Task 11)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ctwa.ui.results.compare_logic import run_colors  # noqa: E402
from ctwa.ui.results.compare_picker import RunPicker  # noqa: E402
from ctwa.ui.results.fmt import run_label_text  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def row(i, **kw):
    r = {"id": i, "model_name": "Stainless Steel", "test_date": "%02d/11/2026" % (i % 28 + 1),
         "temperature_c": 700 + i, "analysis_mode": "Auto", "gas_atmosphere": "Ar", "period_t": 600.0,
         "amplitude_a1": 10.5}
    r.update(kw)
    return r


ROWS = [row(5, model_name="Alumina"), row(3), row(12, temperature_c=766), row(7, temperature_c=766),
        row(9, model_name="Copper")]


@pytest.fixture
def make(qapp):
    made = []

    def _make(rows=ROWS):
        p = RunPicker()
        p.resize(700, 300)
        p.show()
        p.set_rows(rows)
        made.append(p)
        return p
    yield _make
    for p in made:
        p.close()


def type_text(p, text):
    p.edit.clear()
    QTest.keyClicks(p.edit, text)


def test_search_is_and_of_terms_over_label(make):
    p = make()
    type_text(p, "steel 766")
    assert sorted(p.hits()) == [7, 12]
    type_text(p, "#12")
    assert p.hits() == [12]
    type_text(p, "nothing like this")
    assert p.hits() == []


def test_chosen_runs_are_not_offered_again(make):
    p = make()
    p.add(12)
    type_text(p, "steel 766")
    assert p.hits() == [7]


def test_at_most_60_hits(make):
    p = make([row(i) for i in range(1, 100)])
    type_text(p, "steel")
    assert len(p.hits()) == 60


def test_list_is_hidden_without_text(make):
    p = make()
    assert p.hits() == []
    assert p.list.isHidden()
    type_text(p, "a")
    assert not p.list.isHidden()
    QTest.keyClick(p.edit, Qt.Key_Escape)
    assert p.list.isHidden() and p.hits() == []


def test_keys_move_highlight_and_enter_adds(make):
    p = make()
    got = []
    p.ids_changed.connect(got.append)
    type_text(p, "steel")
    hits = p.hits()
    assert len(hits) == 3
    QTest.keyClick(p.edit, Qt.Key_Down)           # highlight starts on the first hit, as the webapp's
    QTest.keyClick(p.edit, Qt.Key_Down)
    QTest.keyClick(p.edit, Qt.Key_Up)
    QTest.keyClick(p.edit, Qt.Key_Down)
    QTest.keyClick(p.edit, Qt.Key_Return)
    assert p.ids() == [hits[2]] and got == [[hits[2]]]
    assert p.edit.text() == ""


def test_enter_adds_first_hit_and_chip_text(make):
    p = make()
    type_text(p, "#703")
    QTest.keyClick(p.edit, Qt.Key_Return)
    assert p.ids() == [3]
    assert p.chip_texts() == [run_label_text(ROWS[1])]


def test_dot_colours_follow_position(make):
    p = make()
    p.add(5)
    p.add(3)
    p.add(9)
    assert p.chip_colors() == [run_colors(i)[0] for i in range(3)]
    p.remove(5)
    assert p.ids() == [3, 9]
    assert p.chip_colors() == [run_colors(0)[0], run_colors(1)[0]]


def test_fifth_add_is_refused(make):
    p = make([row(i) for i in range(1, 8)])
    for i in (1, 2, 3, 4):
        assert p.add(i) is True
    assert p.add(5) is False and p.ids() == [1, 2, 3, 4]
    assert p.counter_text() == "4 / 4"
    assert not p.edit.isEnabled()
    assert p.edit.placeholderText() == "Compare up to 4 at a time"
    p.remove(2)
    assert p.edit.isEnabled() and p.counter_text() == "3 / 4"
    assert p.edit.placeholderText() == "Add a run: type a name, date, °C or #id"


def test_add_unknown_or_duplicate_is_refused(make):
    p = make()
    assert p.add(5) is True and p.add(5) is False and p.add(4242) is False
    assert p.ids() == [5]


def test_set_ids_known_deduplicated_and_capped(make):
    p = make()
    p.set_ids([5, 5, 9999, 3])
    assert p.ids() == [5, 3]
    p.set_ids([5, 3, 12, 7, 9])
    assert p.ids() == [5, 3, 12, 7]


def test_remove_all(make):
    p = make()
    got = []
    p.set_ids([5, 3])
    p.ids_changed.connect(got.append)
    p.remove_all_button.click()
    assert p.ids() == [] and got == [[]]


def test_set_rows_drops_chosen_ids_that_vanished(make):
    p = make()
    p.set_ids([5, 3, 9])
    got = []
    p.ids_changed.connect(got.append)
    p.set_rows([r for r in ROWS if r["id"] != 3])
    assert p.ids() == [5, 9] and got == [[5, 9]]
    p.set_rows(ROWS)
    assert got == [[5, 9]]                         # nothing changed, nothing emitted


def test_title_and_texts(make):
    p = make()
    assert p.title_label.text() == "Select analyses to compare"
    assert p.counter_text() == "0 / 4"
    assert p.edit.placeholderText() == "Add a run: type a name, date, °C or #id"


def test_no_attribute_hides_a_qwidget_member(make):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    assert [n for n in vars(make()) if hasattr(QWidget, n) and not isinstance(getattr(QWidget, n), Signal)] == []
