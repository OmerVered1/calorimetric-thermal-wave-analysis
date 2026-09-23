"""Scenarios run identically against an original per-model window and the
merged window, recording every command sent to the (simulated) instrument.

Used twice: once, by generate_golden(), against the original programs to record
tests/golden/*.json before they were deleted; and on every test run, against the
merged window, which must reproduce those recordings exactly.
"""
import time

SCENARIOS = ("sweep_defaults", "sweep_changed", "multimeter_defaults", "multimeter_changed")


def _record(driver):
    sent = []
    real = driver._write
    driver._write = lambda c: (sent.append(c), real(c))[1]
    return sent


def _wait(app, window, seconds=15):
    t = time.perf_counter()
    while time.perf_counter() - t < seconds:
        app.processEvents()
        time.sleep(0.01)
        if not window.running and time.perf_counter() - t > 0.3:
            return


def _change_settings(window, model):
    """Every setting the per-model windows applied, moved off its default."""
    window.timing_settings.nplc.setValue(2.0)
    window.inst_settings._set_sense("2-Wire" if model == "2450" else "4-Wire")
    ins = window.inst_settings
    if hasattr(ins, "_set_terminal") and model == "2450":
        ins._set_terminal("Front")
    if model == "2450":
        ins.high_cap.setChecked(True)
    if model == "6430":
        ins.guard_mode.setChecked(True)
        ins.output_off_mode.setCurrentText("High-Z")
    if model in ("2450", "6430"):
        window.measure_settings.auto_zero.setCurrentText("Once")


def run(app, window, driver, model, scenario):
    sent = _record(driver)
    if scenario.startswith("sweep"):
        if scenario == "sweep_changed":
            _change_settings(window, model)
        window.source_settings.mode.setCurrentText("Linear Sweep")
        window.sweep_list.start_val.setValue(0.0)
        window.sweep_list.stop_val.setValue(1.0)
        window.sweep_list.num_points.setValue(3)
        window.timing_settings.delay.setValue(0.0)
        window.start_sweep()
        _wait(app, window)
    else:
        mm = window.multimeter_panel
        if scenario == "multimeter_changed":
            mm._set_sense("2-Wire" if model == "2450" else "4-Wire")
            mm.voltage_range.setCurrentIndex(2)
            mm.current_range.setCurrentIndex(mm.current_range.count() - 1)
            if model == "2450":
                # Instrument Settings' terminal; the original multimeter ignored
                # it and used its own selector, which this must reproduce.
                window.inst_settings._set_terminal("Front")
        mm.start_live()
        # Configuration is sent synchronously in start_live; the readings that
        # follow are timing-dependent, so only the set-up is compared.
        n = len(sent)
        mm.stop_live()
        del sent[n:]
    return list(sent)
