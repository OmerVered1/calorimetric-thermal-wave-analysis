"""Saving an analysis: pre-fill, duplicate check, queue, login (offscreen, fake client, no network)."""

from __future__ import annotations

import gzip
import os
import shutil
import time
from datetime import datetime
from urllib.parse import quote

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
    results = run_one_file_pipeline(run.synced, opts)
    return run, opts, results, build_analysis_plot(run.synced, results, opts)


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
        panel.set_run(run_and_results[0])
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
    run, opts, _, _ = run_and_results
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
    assert settings.value("save/last/%s/sample" % quote(experiment, safe="")) == "Alumina"
    # same settings file -> remembered
    from ctwa.ui.save_panel import SavePanel
    p = SavePanel(panel._manager, settings=settings)
    p.set_run(run_and_results[0])
    p.set_result(run_and_results)
    assert p.sample_edit.text() == "Alumina"
    assert p.gas_combo.currentText() == "Air"


def test_save_inserts_exactly_the_built_row(env, run_and_results):
    run, opts, results, plot = run_and_results
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
    expected = build_analysis_row(results, meta, plot)
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
    assert wait(lambda: not panel._busy)
    assert len(panel._manager.client.inserts) == 1
    assert not panel.save_btn.isEnabled()  # stored: Save waits for a NEW result
    panel.set_result(run_and_results)
    assert panel.save_btn.isEnabled()


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


# ---- review round 1 ----

def test_double_click_save_makes_one_insert(env):
    client = FakeClient()
    panel, _, _ = env(client)
    panel.sample_edit.setText("A")
    panel.save_btn.click()
    panel.save_btn.click()
    assert wait(lambda: not panel._busy and client.inserts)
    assert len(client.inserts) == 1


def test_new_result_during_save_keeps_save_disabled_and_remembers_original(env, run_and_results):
    import threading

    class Gated(FakeClient):
        def __init__(self):
            super().__init__()
            self.gate = threading.Event()

        def insert(self, table, row):
            self.gate.wait(5)
            return super().insert(table, row)

    client = Gated()
    panel, _, settings = env(client)
    run, opts, res, plot = run_and_results
    panel.sample_edit.setText("Alumina")
    panel.gas_combo.setCurrentText("Air")
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    assert wait(lambda: not panel.save_btn.isEnabled())
    from types import SimpleNamespace
    other = SimpleNamespace(path=run.path, synced=run.synced, parsed=run.parsed,
                            header=dict(run.header, experiment="Other run"))
    res2 = SimpleNamespace(**res.__dict__)   # a new analysis' results: another object
    panel.set_result((other, opts, res2, plot))
    assert not panel.save_btn.isEnabled()
    panel.save_btn.click()
    client.gate.set()
    assert wait(lambda: got)
    assert wait(lambda: panel.save_btn.isEnabled())  # the NEW result is armed, the old one is not
    assert len(client.inserts) == 1
    exp = run.header["experiment"]
    from urllib.parse import quote
    assert settings.value("save/last/%s/sample" % quote(exp, safe="")) == "Alumina"
    assert settings.value("save/last/%s/sample" % quote("Other run", safe="")) is None


def test_replace_while_offline_is_not_queued(env, monkeypatch):
    class OfflineUpdate(FakeClient):
        def update(self, table, id, data):
            raise Offline("down")

    client = OfflineUpdate()
    panel, mgr, _ = env(client)
    res = panel._results
    client.candidates = [{"id": 7, "model_name": "Alumina", "analysis_mode": "AutoFit",
                          "period_t": res.period_t, "amplitude_a1": res.amplitude_a1}]
    panel.sample_edit.setText("Alumina")
    monkeypatch.setattr(panel, "_ask_duplicate", lambda m: "replace")
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    msg = "Couldn't replace while offline; try again when you're online."
    assert wait(lambda: panel.status_label.text() == msg and panel.save_btn.isEnabled())
    assert mgr.count() == 0 and got == []
    assert panel.sample_edit.text() == "Alumina"


def test_experiment_name_with_slash_does_not_nest(env, run_and_results, tmp_path):
    panel, _, settings = env(FakeClient())
    panel._run.header["experiment"] = "a/b run"
    panel.sample_edit.setText("S")
    save_and_wait(panel)
    assert "a/b run" not in "".join(settings.allKeys()) or "a%2Fb" in "".join(settings.allKeys())
    assert not any(k.startswith("save/last/a/") for k in settings.allKeys())


def test_empty_gas_disables_save_with_hint(env):
    panel, _, _ = env(FakeClient())
    panel.gas_combo.setCurrentText("")
    assert not panel.save_btn.isEnabled()
    assert panel.status_label.text()
    panel.gas_combo.setCurrentText("Ar")
    assert panel.save_btn.isEnabled()


def test_needs_login_emitted_once_while_logged_out(qapp, tmp_path):
    from ctwa.ui.upload_manager import UploadManager
    q = UploadQueue(str(tmp_path / "q"))
    q.enqueue({"model_name": "x"})
    mgr = UploadManager(FakeClient(insert_script=[NotLoggedIn("no")] * 5), q, interval_ms=10 ** 9)
    asked, counts = [], []
    mgr.needs_login.connect(lambda: asked.append(1))
    mgr.count_changed.connect(counts.append)
    mgr.request_flush()
    assert wait(lambda: asked)
    n = len(counts)
    mgr.request_flush()
    assert wait(lambda: len(counts) > n)
    assert asked == [1]
    mgr.login_succeeded()
    n = len(counts)
    mgr.request_flush()
    assert wait(lambda: len(counts) > n)
    assert asked == [1, 1] or mgr.client.insert_script == []
    mgr.shutdown()


def test_login_dialog_cancel_disabled_while_busy(qapp):
    import threading
    from ctwa.ui.login_dialog import LoginDialog

    class Slow(LoginClient):
        def __init__(self):
            super().__init__()
            self.gate = threading.Event()

        def login(self, password):
            self.gate.wait(5)

    c = Slow()
    d = LoginDialog(c)
    d.password_edit.setText("pw")
    d.ok_btn.click()
    assert not d.cancel_btn.isEnabled() and not d.password_edit.isEnabled()
    rejected = []
    d.rejected.connect(lambda: rejected.append(1))
    d.reject()  # Esc while busy is ignored
    assert rejected == []
    c.gate.set()
    assert wait(lambda: d.result() == QDialog.Accepted)


def test_successful_login_rearms_manager(env, monkeypatch):
    import ctwa.ui.save_panel as sp
    client = FakeClient(insert_script=[NotLoggedIn("no")])

    class Ok:
        def __init__(self, c, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(sp, "LoginDialog", Ok)
    panel, mgr, _ = env(client)
    mgr._login_asked = True
    panel.sample_edit.setText("A")
    save_and_wait(panel)
    assert mgr._login_asked is False


def test_replace_then_login_cancelled_is_not_queued(env, monkeypatch):
    import ctwa.ui.save_panel as sp

    class LoggedOutUpdate(FakeClient):
        def update(self, table, id, data):
            raise NotLoggedIn("no")

    class Cancel:
        def __init__(self, c, parent=None):
            pass

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(sp, "LoginDialog", Cancel)
    client = LoggedOutUpdate()
    panel, mgr, _ = env(client)
    res = panel._results
    client.candidates = [{"id": 7, "model_name": "Alumina", "analysis_mode": "AutoFit",
                          "period_t": res.period_t, "amplitude_a1": res.amplitude_a1}]
    panel.sample_edit.setText("Alumina")
    monkeypatch.setattr(panel, "_ask_duplicate", lambda m: "replace")
    got = []
    panel.saved.connect(got.append)
    panel.save_btn.click()
    assert wait(lambda: panel.status_label.text() == "Not replaced: you're not logged in."
                and panel.save_btn.isEnabled())
    assert mgr.count() == 0 and got == []
    assert panel.sample_edit.text() == "Alumina"


# ---- final fix wave: Save never stays armed with a stale result ----

def test_clear_result_disables_save_and_keeps_typed_values(env):
    panel, _, _ = env(FakeClient())
    panel.sample_edit.setText("Alumina")
    assert panel.save_btn.isEnabled()
    panel.clear_result()
    assert not panel.save_btn.isEnabled()
    assert panel._results is None and panel._plot is None
    assert panel.sample_edit.text() == "Alumina"
    panel.save_btn.click()  # nothing to save: no job, nothing sent
    assert panel._manager.client.inserts == [] and not panel._busy


def test_second_save_without_a_new_result_is_impossible(env, run_and_results):
    client = FakeClient()
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    save_and_wait(panel)
    assert not panel.save_btn.isEnabled()
    panel.save_btn.click()
    assert len(client.inserts) == 1
    panel.set_result(run_and_results)  # a new result re-arms it
    assert panel.save_btn.isEnabled()


def test_queued_save_also_disarms_save(env, run_and_results):
    client = FakeClient(select_exc=Offline("down"), insert_script=[Offline("down")])
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    save_and_wait(panel)
    assert mgr.count() == 1
    assert not panel.save_btn.isEnabled()
    panel.save_btn.click()
    assert mgr.count() == 1  # no second queued row


def test_new_result_arriving_during_a_save_stays_armed_after_it(env, run_and_results):
    client = FakeClient()
    panel, mgr, _ = env(client)
    panel.sample_edit.setText("A")
    panel.save_btn.click()
    run, opts, res, plot = run_and_results
    other = object.__new__(type(res))
    other.__dict__.update(res.__dict__)
    panel.set_result((run, opts, other, plot))
    assert wait(lambda: not panel._busy)
    assert panel._results is other and panel.save_btn.isEnabled()


def test_date_and_time_are_saved_zero_padded(env):
    client = FakeClient()
    panel, _, _ = env(client)
    panel.sample_edit.setText("A")
    panel.date_edit.setText("1/2/2026")
    panel.time_edit.setText("9:5")
    save_and_wait(panel)
    assert client.selects[0][1]["test_date"] == "eq.01/02/2026"
    assert client.inserts[0]["test_date"] == "01/02/2026"
    assert client.inserts[0]["test_time"] == "09:05"


def test_enqueue_failure_shows_the_error_and_keeps_the_form(env):
    client = FakeClient(select_exc=Offline("down"), insert_script=[Offline("down")])
    panel, mgr, _ = env(client)

    def boom(row):
        raise OSError("disk full")
    mgr.enqueue = boom
    panel.sample_edit.setText("Keep me")
    panel.save_btn.click()
    assert wait(lambda: "disk full" in panel.status_label.text())
    assert not panel._busy
    assert panel.sample_edit.text() == "Keep me" and panel.sample_edit.isEnabled()
    assert panel.save_btn.isEnabled()  # the result is still armed for another try


# ---- experiment details in the run header (Task 4) ----

def _with_header(run_and_results, **header):
    """The same result, with the run's header extended (and optionally a run without temperatures)."""
    import copy
    run, opts, results, plot = run_and_results
    run2 = copy.copy(run)
    run2.header = dict(run.header, **header)
    return run2, opts, results, plot


def test_header_details_win_over_the_old_sources(env, run_and_results):
    panel, _, settings = env(FakeClient())
    experiment = run_and_results[0].header["experiment"]
    settings.setValue("save/last/%s/sample" % quote(experiment, safe=""), "Remembered")
    settings.setValue("save/last/%s/gas" % quote(experiment, safe=""), "Air")
    payload = _with_header(run_and_results, sample="Al2O3", gas="He", power_source="PS-1",
                           response_device="Cal-1")
    panel.set_run(payload[0])
    assert panel.sample_edit.text() == "Al2O3"
    assert panel.gas_combo.currentText() == "He"
    assert panel.source_device_edit.text() == "PS-1"
    assert panel.response_device_edit.text() == "Cal-1"


def test_no_header_details_fall_back_to_memory_and_old_sources(env, run_and_results):
    panel, _, settings = env(FakeClient())
    experiment = run_and_results[0].header["experiment"]
    settings.setValue("save/last/%s/sample" % quote(experiment, safe=""), "Remembered")
    settings.setValue("save/last/%s/gas" % quote(experiment, safe=""), "Air")
    panel.set_run(_with_header(run_and_results, sample=None, gas=None, power_source=None,
                               response_device=None)[0])
    assert panel.sample_edit.text() == "Remembered"
    assert panel.gas_combo.currentText() == "Air"
    assert panel.source_device_edit.text() == "Keithley 2602B"
    assert panel.response_device_edit.text() == "Drop Calorimeter"
    # and with no memory either: gas defaults to Ar, sample blank
    other = _with_header(run_and_results, experiment="never saved before", sample=None, gas=None)
    panel.set_run(other[0])
    assert panel.sample_edit.text() == "" and panel.gas_combo.currentText() == "Ar"


def test_measured_temperature_wins_over_the_header(env, run_and_results):
    panel, _, _ = env(FakeClient())
    run, opts, _, _ = run_and_results
    payload = _with_header(run_and_results, temperature_c=999.0)
    panel.set_run(payload[0])
    assert panel.temperature_edit.text() == "999"
    panel.set_result(payload)
    measured = panel.temperature_edit.text()
    assert measured and measured != "999"


def test_header_temperature_is_used_when_the_run_has_no_temperature_column(env, run_and_results):
    from types import SimpleNamespace
    panel, _, _ = env(FakeClient())
    run, opts, results, plot = _with_header(run_and_results, temperature_c=800.5)
    run.parsed = SimpleNamespace(time=list(run.parsed.time),
                                 temperature=[float("nan")] * len(run.parsed.time))
    panel.set_run(run)
    panel.set_result((run, opts, results, plot))
    assert panel.temperature_edit.text() == "800.5"
    run.header["temperature_c"] = None
    panel.set_run(run)
    panel.set_result((run, opts, results, plot))
    assert panel.temperature_edit.text() == ""


# ---- steps: the form and the save part are placed by the tab ----

def test_set_run_prefills_before_any_result(env, run_and_results):
    from ctwa.ui.save_panel import SavePanel
    _, mgr, settings = env(FakeClient())
    p = SavePanel(mgr, settings=settings)
    p.set_run(_with_header(run_and_results, temperature_c=801.0, sample="Al2O3", gas="He")[0])
    assert p.date_edit.text() == "17/11/2026" and p.time_edit.text() == "09:10"
    assert p.source_device_edit.text() == "Keithley 2602B"
    assert p.sample_edit.text() == "Al2O3" and p.gas_combo.currentText() == "He"
    assert p.temperature_edit.text() == "801"
    assert not p.save_btn.isEnabled()
    p.set_run(_with_header(run_and_results, temperature_c=None)[0])
    assert p.temperature_edit.text() == ""


def test_typed_temperature_survives_set_result(env, run_and_results):
    panel, _, _ = env(FakeClient())
    panel.set_run(run_and_results[0])
    panel.temperature_edit.clear()
    from PySide6.QtTest import QTest
    QTest.keyClicks(panel.temperature_edit, "123.4")
    panel.set_result(run_and_results)
    assert panel.temperature_edit.text() == "123.4"
    panel.set_run(run_and_results[0])  # a new run forgets what was typed
    panel.set_result(run_and_results)
    assert panel.temperature_edit.text() != "123.4"


def test_untouched_temperature_follows_each_result(env, run_and_results):
    import copy
    panel, _, _ = env(FakeClient())
    run, opts, results, plot = run_and_results
    measured = panel.temperature_edit.text()
    assert measured
    opts2 = copy.copy(opts)
    opts2.sel_max = opts.sel_min + (opts.sel_max - opts.sel_min) / 2
    from ctwa.ui.save_panel import region_temperature
    expected = region_temperature(run.parsed, opts2.sel_min, opts2.sel_max)
    panel.set_result((run, opts2, results, plot))
    assert panel.temperature_edit.text() == expected


def test_saving_line_text_and_dashes(env):
    panel, _, _ = env(FakeClient())
    panel.sample_edit.setText("Alumina")
    panel.temperature_edit.setText("766.2")
    panel.gas_combo.setCurrentText("Air")
    assert panel.saving_label.text() == "Saving as: Alumina · 17/11/2026 09:10 · 766.2 °C · Air"
    panel.sample_edit.setText("")
    panel.temperature_edit.setText("")
    assert panel.saving_label.text() == "Saving as: — · 17/11/2026 09:10 · — · Air"


def test_edit_link_emits_edit_requested(env):
    panel, _, _ = env(FakeClient())
    got = []
    panel.edit_requested.connect(lambda: got.append(1))
    panel.edit_btn.click()
    assert got == [1]


def test_busy_save_disables_both_parts(env):
    import threading

    class Gated(FakeClient):
        def __init__(self):
            super().__init__()
            self.gate = threading.Event()

        def insert(self, table, row):
            self.gate.wait(5)
            return super().insert(table, row)

    client = Gated()
    panel, _, _ = env(client)
    panel.sample_edit.setText("A")
    panel.save_btn.click()
    assert wait(lambda: panel._busy)
    assert not panel.form_widget.isEnabled() or not panel.sample_edit.isEnabled()
    assert not panel.sample_edit.isEnabled() and not panel.temperature_edit.isEnabled()
    assert not panel.gas_combo.isEnabled() and not panel.save_btn.isEnabled()
    client.gate.set()
    assert wait(lambda: not panel._busy)
    assert panel.sample_edit.isEnabled()
