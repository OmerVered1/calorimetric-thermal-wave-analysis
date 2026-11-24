"""Saving an analysis: pre-fill, duplicate check, queue, login (offscreen, fake client, no network)."""

from __future__ import annotations

import gzip
import os
import shutil
import time
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from ctwa.analysis.pipeline import run_one_file_pipeline  # noqa: E402
from ctwa.analysis.row import RowMeta, build_analysis_plot, build_analysis_row  # noqa: E402
from ctwa.analysis.runner import load_run  # noqa: E402
from ctwa.analysis.types import AnalysisParams, PipelineOptions  # noqa: E402
from ctwa.cloud.client import NotLoggedIn, Offline, ServerError  # noqa: E402
from ctwa.cloud.queue import UploadQueue  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def run_and_results(tmp_path_factory):
    out = tmp_path_factory.mktemp("sp") / "al2o3_ctwa.csv"
    with gzip.open(os.path.join(HERE, "data", "runs", "al2o3_ctwa.csv.gz"), "rb") as s, open(out, "wb") as d:
        shutil.copyfileobj(s, d)
    run = load_run(str(out))
    lo, hi, _ = run.default
    params = AnalysisParams(
        model_name="", test_date="", test_time="", t_cal="00:00:00", t_src="00:00:00",
        r1_mm=6.72, r2_mm=14.86, c80_time_unit="Seconds", c80_pwr_unit="mW",
        src_time_unit="Seconds", src_pwr_unit="mW", use_calibration=False, system_lag=0.0,
        analysis_mode="AutoFit")
    opts = PipelineOptions(wave_type="sine", smooth_to_sine=False, sel_min=lo, sel_max=hi, params=params)
    return run, opts, run_one_file_pipeline(run.synced, opts)


class FakeClient:
    def __init__(self, candidates=None, select_exc=None, insert_script=None):
        self.candidates = candidates or []
        self.select_exc = select_exc
        self.insert_script = list(insert_script or [])
        self.selects, self.inserts, self.updates = [], [], []

    def select(self, table, query):
        self.selects.append((table, dict(query)))
        if self.select_exc:
            raise self.select_exc
        return list(self.candidates)

    def insert(self, table, row):
        if self.insert_script:
            a = self.insert_script.pop(0)
            if a is not None:
                raise a
        self.inserts.append(row)
        return dict(row, id=100 + len(self.inserts))

    def update(self, table, id, data):
        self.updates.append((id, data))
        return dict(data, id=id)

    def login(self, password):
        pass


def wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def env(qapp, tmp_path, run_and_results):
    from ctwa.ui.save_panel import SavePanel
    from ctwa.ui.upload_manager import UploadManager

    made = []

    def build(client):
        settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
        mgr = UploadManager(client, UploadQueue(str(tmp_path / "q")), interval_ms=10 ** 9)
        panel = SavePanel(mgr, settings=settings)
        made.append((panel, mgr))
        panel.set_result(run_and_results)
        return panel, mgr, settings

    yield build
    for panel, mgr in made:
        mgr.shutdown()
        QThreadPool.globalInstance().waitForDone(3000)


def save_and_wait(panel):
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    assert wait(lambda: len(got) == 1)
    return got


def test_prefill_from_header(env, run_and_results):
    panel, _, _ = env(FakeClient())
    run, opts, _ = run_and_results
    assert panel.date_edit.text() == "17/11/2026"
    assert panel.time_edit.text() == "09:10"
    assert panel.source_device_edit.text() == "Keithley 2602B"
    assert panel.response_device_edit.text() == "Drop Calorimeter"
    assert panel.sample_edit.text() == ""
    assert panel.gas_combo.currentText() == "Ar"
    ts = [t for t, v in zip(run.parsed.time, run.parsed.temperature)
          if opts.sel_min <= t <= opts.sel_max and v == v]
    vs = [v for t, v in zip(run.parsed.time, run.parsed.temperature)
          if opts.sel_min <= t <= opts.sel_max and v == v]
    assert panel.temperature_edit.text() == "%.1f" % (sum(vs) / len(vs))
    assert ts


def test_device_helpers():
    from ctwa.ui.save_panel import calorimeter_device, instrument_device
    assert instrument_device("Keithley Instruments Inc., Model 2602B, 1, 3.2.2") == "Keithley 2602B"
    assert instrument_device("Something else") == ""
    assert instrument_device(None) == ""
    assert calorimeter_device("Drop (Alexsys) @ 1.2.3.4  channels=hf") == "Drop Calorimeter"
    assert calorimeter_device("Alexsys thing") == "Drop Calorimeter"
    assert calorimeter_device("Setaram C80 @ x") == "C80"
    assert calorimeter_device("Other box @ 1.1.1.1 ch") == "Other box"
    assert calorimeter_device(None) == ""


def test_temperature_empty_without_finite_values():
    from types import SimpleNamespace
    from ctwa.ui.save_panel import region_temperature
    parsed = SimpleNamespace(time=[1.0, 2.0], temperature=[float("nan"), float("nan")])
    assert region_temperature(parsed, 0, 10) == ""
    parsed = SimpleNamespace(time=[1.0, 2.0, 30.0], temperature=[10.0, 11.0, 99.0])
    assert region_temperature(parsed, 0, 10) == "10.5"


def test_sample_and_gas_remembered_per_experiment(env, run_and_results):
    client = FakeClient()
    panel, _, settings = env(client)
    panel.sample_edit.setText("Alumina")
    panel.gas_combo.setCurrentText("Air")
    save_and_wait(panel)
    experiment = run_and_results[0].header["experiment"]
    assert settings.value("save/last/%s/sample" % experiment) == "Alumina"
    # same settings file -> remembered
    from ctwa.ui.save_panel import SavePanel
    p = SavePanel(panel._manager, settings=settings)
    p.set_result(run_and_results)
    assert p.sample_edit.text() == "Alumina"
    assert p.gas_combo.currentText() == "Air"


def test_save_inserts_exactly_the_built_row(env, run_and_results):
    run, opts, results = run_and_results
    client = FakeClient()
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("Alumina ")
    panel.temperature_edit.setText("766.2")
    got = save_and_wait(panel)
    assert got == [101]
    assert len(client.inserts) == 1 and client.updates == []
    meta = RowMeta(model_name="Alumina ", test_date="17/11/2026", test_time="09:10", temperature=766.2,
                   gas_atmosphere="Ar", power_source_device="Keithley 2602B",
                   power_response_device="Drop Calorimeter", wave_type="sine", analysis_mode="AutoFit",
                   r1=6.72, r2=14.86, use_calibration=False, system_lag=0.0, input_mode="one",
                   source_file_name="al2o3_ctwa.csv")
    expected = build_analysis_row(results, meta, build_analysis_plot(run.synced, results, opts))
    assert client.inserts[0] == expected
    assert client.inserts[0]["model_name"] == "Alumina"
    assert client.selects[0][1]["test_date"] == "eq.17/11/2026"
    assert mgr.count() == 0


def test_save_button_gating(env, run_and_results):
    from ctwa.ui.save_panel import SavePanel
    panel, mgr, _ = env(FakeClient())
    fresh = SavePanel(mgr, settings=panel._settings)
    assert not fresh.save_btn.isEnabled()
    panel.sample_edit.setText("A")
    panel.save_btn.click()
    assert not panel.save_btn.isEnabled()  # in flight
    panel.save_btn.click()  # double click does nothing
    assert wait(lambda: panel.save_btn.isEnabled())
    assert len(panel._manager.client.inserts) == 1


def test_duplicate_cancel_sends_nothing(env, monkeypatch):
    cand = [{"id": 7, "model_name": "alumina", "analysis_mode": "AutoFit", "period_t": 0, "amplitude_a1": 0}]
    client = FakeClient(candidates=cand)
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("Alumina")
    # make the candidate close to the result
    res = panel._results
    cand[0]["period_t"], cand[0]["amplitude_a1"] = res.period_t, res.amplitude_a1
    asked = []
    monkeypatch.setattr(panel, "_ask_duplicate", lambda m: asked.append(m) or "cancel")
    panel.save_btn.click()
    assert wait(lambda: asked and panel.save_btn.isEnabled())
    assert asked[0]["id"] == 7
    assert client.inserts == [] and client.updates == [] and mgr.count() == 0


def test_duplicate_replace_updates_existing(env, monkeypatch):
    client = FakeClient()
    panel, _, _ = env(client)
    res = panel._results
    client.candidates = [{"id": 7, "model_name": "Alumina", "analysis_mode": "AutoFit",
                          "period_t": res.period_t, "amplitude_a1": res.amplitude_a1}]
    panel.sample_edit.setText("Alumina")
    monkeypatch.setattr(panel, "_ask_duplicate", lambda m: "replace")
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    assert wait(lambda: got)
    assert got == [7]
    assert client.inserts == [] and len(client.updates) == 1 and client.updates[0][0] == 7
    assert client.updates[0][1]["model_name"] == "Alumina"


def test_duplicate_save_as_new_inserts(env, monkeypatch):
    client = FakeClient()
    panel, _, _ = env(client)
    res = panel._results
    client.candidates = [{"id": 7, "model_name": "Alumina", "analysis_mode": "AutoFit",
                          "period_t": res.period_t, "amplitude_a1": res.amplitude_a1}]
    panel.sample_edit.setText("Alumina")
    monkeypatch.setattr(panel, "_ask_duplicate", lambda m: "new")
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    assert wait(lambda: got)
    assert got == [101] and len(client.inserts) == 1 and client.updates == []


def test_offline_insert_is_queued(env):
    client = FakeClient(insert_script=[Offline("down")])
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    counts = []
    mgr.count_changed.connect(counts.append)
    got = save_and_wait(panel)
    assert got == [None]
    assert mgr.count() == 1 and counts[-1] == 1
    assert "will upload when online" in panel.status_label.text()
    assert client.inserts == []


def test_offline_duplicate_check_is_skipped_and_row_queued(env):
    client = FakeClient(select_exc=Offline("down"))
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    got = save_and_wait(panel)
    assert got == [None] and mgr.count() == 1 and client.inserts == []


def test_not_logged_in_shows_login_then_retries_once(env, monkeypatch):
    import ctwa.ui.save_panel as sp
    client = FakeClient(insert_script=[NotLoggedIn("no")])
    shown = []

    class AutoLogin:
        def __init__(self, c, parent=None):
            shown.append(c)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(sp, "LoginDialog", AutoLogin)
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    got = save_and_wait(panel)
    assert shown == [client]
    assert got == [101] and len(client.inserts) == 1 and mgr.count() == 0


def test_login_cancelled_queues(env, monkeypatch):
    import ctwa.ui.save_panel as sp
    client = FakeClient(insert_script=[NotLoggedIn("no")])

    class Cancel:
        def __init__(self, c, parent=None):
            pass

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(sp, "LoginDialog", Cancel)
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    got = save_and_wait(panel)
    assert got == [None] and mgr.count() == 1


def test_login_then_second_failure_queues_without_looping(env, monkeypatch):
    import ctwa.ui.save_panel as sp
    client = FakeClient(insert_script=[NotLoggedIn("no"), NotLoggedIn("again")])
    n = []

    class Ok:
        def __init__(self, c, parent=None):
            n.append(1)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(sp, "LoginDialog", Ok)
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    got = save_and_wait(panel)
    assert got == [None] and len(n) == 1 and mgr.count() == 1


def test_server_error_keeps_form_and_does_not_queue(env):
    client = FakeClient(insert_script=[ServerError(400, "bad column")])
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("Keep me")
    panel.save_btn.click()
    assert wait(lambda: panel.save_btn.isEnabled() and "bad column" in panel.status_label.text())
    assert panel.sample_edit.text() == "Keep me"
    assert mgr.count() == 0


def test_validation_blocks_empty_sample(env):
    client = FakeClient()
    panel, _, _ = env(client)
    panel.save_btn.click()
    assert client.selects == [] and panel.save_btn.isEnabled()
    assert panel.status_label.text()


# ---- UploadManager ----

def test_manager_flushes_on_start_and_emits_count(qapp, tmp_path):
    from ctwa.ui.upload_manager import UploadManager
    q = UploadQueue(str(tmp_path / "q"))
    q.enqueue({"model_name": "x"})
    client = FakeClient()
    mgr = UploadManager(client, q, interval_ms=10 ** 9)
    counts = []
    mgr.count_changed.connect(counts.append)
    mgr.start()
    assert wait(lambda: counts and counts[-1] == 0)
    assert client.inserts == [{"model_name": "x"}]
    mgr.shutdown()


def test_manager_needs_login_when_flush_unauthorised(qapp, tmp_path):
    from ctwa.ui.upload_manager import UploadManager
    q = UploadQueue(str(tmp_path / "q"))
    q.enqueue({"model_name": "x"})
    mgr = UploadManager(FakeClient(insert_script=[NotLoggedIn("no")]), q, interval_ms=10 ** 9)
    asked = []
    mgr.needs_login.connect(lambda: asked.append(1))
    mgr.start()
    assert wait(lambda: asked)
    assert mgr.count() == 1
    mgr.shutdown()


def test_manager_timer_flushes(qapp, tmp_path):
    from ctwa.ui.upload_manager import UploadManager
    q = UploadQueue(str(tmp_path / "q"))
    client = FakeClient()
    mgr = UploadManager(client, q, interval_ms=30)
    mgr.start()
    q.enqueue({"a": 1})
    assert wait(lambda: client.inserts == [{"a": 1}])
    mgr.shutdown()


# ---- LoginDialog ----

class LoginClient:
    def __init__(self, exc=None):
        self.exc, self.passwords = exc, []

    def login(self, password):
        self.passwords.append(password)
        if self.exc:
            raise self.exc


def test_login_dialog_wrong_password(qapp):
    from PySide6.QtWidgets import QLineEdit
    from ctwa.ui.login_dialog import LoginDialog
    d = LoginDialog(LoginClient(NotLoggedIn("x")))
    assert d.password_edit.echoMode() == QLineEdit.Password
    d.password_edit.setText("wrong")
    d.ok_btn.click()
    assert wait(lambda: d.error_label.text() == "Incorrect password")
    assert d.result() != QDialog.Accepted
    assert d.password_edit.text() == ""  # not kept


def test_login_dialog_offline_and_success(qapp):
    from ctwa.ui.login_dialog import LoginDialog
    d = LoginDialog(LoginClient(Offline("x")))
    d.password_edit.setText("pw")
    d.ok_btn.click()
    assert wait(lambda: "offline" in d.error_label.text().lower() or "connect" in d.error_label.text().lower())
    c = LoginClient()
    d2 = LoginDialog(c)
    d2.password_edit.setText("right")
    d2.ok_btn.click()
    assert wait(lambda: d2.result() == QDialog.Accepted)
    assert c.passwords == ["right"]
