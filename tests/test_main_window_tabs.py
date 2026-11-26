"""The Runs and Analysis tabs, the save panel and the upload queue in the main window."""

import gzip
import logging
import os
import shutil
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "data", "runs")


@pytest.fixture(scope="module")
def app():
    logging.disable(logging.CRITICAL)
    for n in ("warning", "critical", "information"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: None))
    return QApplication.instance() or QApplication([])


def pump(app, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


@pytest.fixture
def window(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.auto_save_enabled = False
    w.auto_save_path = str(tmp_path)
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    yield w
    w.stop_sweep()
    pump(app, 0.3)
    w.close()


def tab_names(w):
    return [w.tabs.tabText(i) for i in range(w.tabs.count())]


def test_runs_and_analysis_tabs_follow_real_time(window):
    names = tab_names(window)
    i = names.index("Real Time")
    assert names[i:i + 6] == ["Real Time", "Runs", "Analysis", "Calibration", "Results", "Statistics"]


def test_opening_a_run_switches_to_analysis_and_loads_it(app, window, tmp_path):
    out = tmp_path / "al2o3_ctwa.csv"
    with gzip.open(os.path.join(RUNS_DIR, "al2o3_ctwa.csv.gz"), "rb") as s, open(out, "wb") as d:
        shutil.copyfileobj(s, d)
    window.runs_tab.open_run.emit(str(out))
    assert window.tabs.currentWidget() is window.analysis_tab
    assert pump(app, 30, until=lambda: window.analysis_tab.run is not None)


def test_a_running_sweep_marks_its_csv_as_recording(app, window):
    w = window
    w.source_settings.mode.setCurrentText("Linear Sweep")
    w.sweep_list.start_val.setValue(0.0)
    w.sweep_list.stop_val.setValue(1.0)
    w.sweep_list.num_points.setValue(10)
    w.timing_settings.delay.setValue(0.0)
    w.timing_settings.step_size.setValue(0.2)
    w.timing_settings.auto_delay_check.setChecked(True)
    w.start_sweep()
    assert pump(app, 5, until=lambda: w._live_csv_path is not None)
    assert os.path.normcase(os.path.abspath(w._live_csv_path)) == w.runs_tab.model.recording
    w.stop_sweep()
    assert pump(app, 5, until=lambda: w.runs_tab.model.recording is None)


def test_changing_the_auto_save_folder_updates_the_runs_tab(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    new = tmp_path / "elsewhere"
    new.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(new)))
    window._set_auto_save_path()
    assert window.runs_tab.auto_save_dir == str(new)


def test_save_panel_sits_in_the_analysis_tab_and_gets_results(window):
    # the save panel is split: the form sits on the Setup page, the save part on the Results page
    assert window.analysis_tab.isAncestorOf(window.save_panel.form_widget)
    assert window.analysis_tab.isAncestorOf(window.save_panel.action_widget)
    window.analysis_tab.result_ready.emit(("run", "opts", "results", None))
    assert window.save_panel._results == "results"


def test_queue_count_shows_in_the_status_bar(window):
    lab = window.upload_label
    window.upload_manager.count_changed.emit(3)
    assert lab.text() == "3 waiting to upload" and not lab.isHidden()
    window.upload_manager.count_changed.emit(0)
    assert lab.isHidden()


def test_needs_login_shows_a_message_without_a_dialog(window, monkeypatch):
    from ctwa.ui import login_dialog
    opened = []
    monkeypatch.setattr(login_dialog.LoginDialog, "exec", lambda self: opened.append(1) or 0)
    window.upload_manager.needs_login.emit()
    assert not opened
    assert window.login_button.text() == "Log in\u2026"


def test_webapp_login_menu_entry_exists_and_success_notifies_the_manager(window, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from ctwa.ui import login_dialog
    texts = [a.text() for m in window.menuBar().actions() if m.menu()
             for a in m.menu().actions()]
    assert any(t.startswith("Webapp login") for t in texts)
    called = []
    window.upload_manager.login_succeeded = lambda: called.append(1)
    monkeypatch.setattr(login_dialog.LoginDialog, "exec", lambda self: QDialog.Accepted)
    window._webapp_login()
    assert called


def test_keyring_is_not_imported_by_creating_the_window(window):
    assert "keyring" not in sys.modules


def test_closing_shuts_the_background_workers_down(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.close()
    assert w.upload_manager._closed
    assert w.save_panel._closed
    assert w.analysis_tab.worker._executor is None
    w.close()   # a second close must not raise


def test_the_real_cloud_services_build_offline_without_keyring(monkeypatch, tmp_path):
    """The factory the app really uses: a client and a queue in a scratch folder, no network,
    and the keyring is only needed when a token is asked for."""
    from ctwa import app as appmod
    from ctwa.cloud import queue as cloud_queue
    monkeypatch.setitem(sys.modules, "keyring", None)   # importing it would raise
    monkeypatch.setattr(cloud_queue, "default_queue_folder", lambda: str(tmp_path / "q"))
    client, queue = appmod._real_make_cloud_services()
    assert (tmp_path / "q").is_dir()
    assert queue.pending() == []
    assert client is not None and "keyring" in sys.modules and sys.modules["keyring"] is None


def test_the_window_opens_when_the_cloud_services_cannot_start(app, tmp_path, monkeypatch):
    from ctwa import app as appmod

    def broken():
        raise RuntimeError("no keyring here\nsecond line")
    monkeypatch.setattr(appmod, "_make_cloud_services", broken)
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    try:
        assert w.upload_manager is None and w.save_panel is None and w.cloud_client is None
        assert w.status.currentMessage() == "Cloud features off: no keyring here"
        assert w.runs_tab.client is None
        names = tab_names(w)
        i = names.index("Runs")
        assert names[i:i + 5] == ["Runs", "Analysis", "Calibration", "Results", "Statistics"]
    finally:
        w.close()   # closing without a manager or panel must not raise


def test_closing_turns_the_outputs_off_before_stopping_the_helpers(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    order = []
    real_off = w.smu.all_outputs_off
    w.smu.all_outputs_off = lambda: (order.append("outputs_off"), real_off())[1]
    real_um = w.upload_manager.shutdown
    w.upload_manager.shutdown = lambda *a, **k: (order.append("upload_shutdown"), order.append(a), real_um(*a, **k))[2]
    real_rt = w.runs_tab.shutdown
    w.runs_tab.shutdown = lambda: (order.append("runs_shutdown"), real_rt())[1]
    w.close()
    assert order[0] == "outputs_off"
    assert order.index("upload_shutdown") > 0 and order.index("runs_shutdown") > 0
    assert order[order.index("upload_shutdown") + 1][0] <= 500   # a short wait, not 5 s


def test_a_failing_recording_lock_cannot_drop_the_live_csv_writer(app, window, monkeypatch):
    w = window

    real = w.runs_tab.set_recording_path

    def boom(p):
        if p is not None:
            raise RuntimeError("runs tab broke")
        real(p)
    monkeypatch.setattr(w.runs_tab, "set_recording_path", boom)
    w.source_settings.mode.setCurrentText("Linear Sweep")
    w.sweep_list.start_val.setValue(0.0)
    w.sweep_list.stop_val.setValue(1.0)
    w.sweep_list.num_points.setValue(5)
    w.timing_settings.delay.setValue(0.0)
    w.timing_settings.step_size.setValue(0.2)
    w.timing_settings.auto_delay_check.setChecked(True)
    w.start_sweep()
    assert pump(app, 5, until=lambda: w._live_csv_path is not None)
    assert w._live_csv_writer is not None
    w.stop_sweep()
    pump(app, 1)


def test_analysis_tab_pages_fit_without_scrolling_at_1400x900(app, window, tmp_path):
    window.resize(1400, 900)
    window.show()
    window.tabs.setCurrentWidget(window.analysis_tab)
    pump(app, 0.5)
    tab = window.analysis_tab
    view = tab.splitter.widget(1).viewport()

    def fits(btn):
        top = btn.mapTo(view, btn.rect().topLeft()).y()
        bottom = btn.mapTo(view, btn.rect().bottomLeft()).y()
        return top >= 0 and bottom <= view.height()

    # Setup: no plot, the form and the settings get the height; Next is in view
    assert tab.step() == "setup" and not tab.plot.isVisibleTo(tab)
    assert fits(tab.next_region_btn)
    # Region: a roomy plot, Analyze in view
    out = tmp_path / "al2o3_ctwa.csv"
    with gzip.open(os.path.join(RUNS_DIR, "al2o3_ctwa.csv.gz"), "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    tab.open_run(str(out))
    assert pump(app, 30, lambda: tab.run is not None)
    tab.go("region")
    pump(app, 0.5)
    sizes = tab.splitter.sizes()
    assert sizes[0] / sum(sizes) >= 0.30
    assert fits(tab.analyze_btn)


def test_closing_sets_the_abort_flag_before_the_outputs_go_off(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    seen = []
    real_off = w.smu.all_outputs_off
    w.smu.all_outputs_off = lambda: (seen.append(w.abort_flag), real_off())[1]
    w.close()
    assert seen == [True]


@pytest.mark.parametrize("victim", [
    "save_panel.shutdown", "upload_manager.shutdown", "results_loader.shutdown",
    "runs_tab.shutdown", "analysis_tab.worker.shutdown", "results_tab.flush_pending"])
def test_a_helper_failing_during_close_cannot_skip_the_instrument_teardown(app, tmp_path, victim):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    calls = []
    obj = w
    *path, attr = victim.split(".")
    for p in path:
        obj = getattr(obj, p)

    def boom(*a, **k):
        raise RuntimeError("helper failed")
    setattr(obj, attr, boom)
    smu = w.smu
    real_dis = smu.disconnect
    smu.disconnect = lambda: (calls.append("smu.disconnect"), real_dis())[1]
    real_stop = w.multimeter_panel.stop_live
    w.multimeter_panel.stop_live = lambda: (calls.append("stop_live"), real_stop())[1]
    w.close()
    assert calls == ["stop_live", "smu.disconnect"]


def test_the_calorimeter_disconnect_still_runs_when_stop_live_fails(app, tmp_path):
    from ctwa import app as appmod
    appmod.MainWindow._check_license_agreement = lambda self: True
    w = appmod.MainWindow()
    w.connect_instrument("2602B", simulate=True, simulation_resistance=100.0)
    calls = []
    w.multimeter_panel.stop_live = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    w.calorimeter_reader = object()
    w.disconnect_calorimeter = lambda: calls.append("cal")
    smu = w.smu
    real_dis = smu.disconnect
    smu.disconnect = lambda: (calls.append("smu"), real_dis())[1]
    w.close()
    assert calls == ["cal", "smu"]
