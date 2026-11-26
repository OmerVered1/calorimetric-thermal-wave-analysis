"""The results list shows the source and the response period and frequency separately."""
from __future__ import annotations

from types import SimpleNamespace

from ctwa.ui.analysis_results import ROWS, format_results

_BASE = dict(alpha_phase_raw=1e-6, alpha_phase_cal=1e-6, alpha_combined_raw=1e-6, alpha_combined_cal=1e-6,
             net_lag_dt=10.0, lag_se=None, amplitude_a1=5.0, amplitude_a2=2.0, ln_term=0.9)


def test_rows_have_source_and_response_period_and_frequency():
    labels = dict((k, (l, u)) for k, l, u in ROWS)
    assert labels["period"] == ("Source Period T", "s")
    assert labels["period_resp"] == ("Response Period T", "s")
    assert labels["freq"] == ("Source Frequency f", "Hz")
    assert labels["freq_resp"] == ("Response Frequency f", "Hz")
    keys = [k for k, _, _ in ROWS]
    assert keys[keys.index("period"):keys.index("period") + 4] == ["period", "period_resp", "freq", "freq_resp"]


def test_formatted_values():
    r = SimpleNamespace(period_t=600.123, period_t_resp=600.456, frequency_f=0.00166633,
                        frequency_f_resp=0.0016654, **_BASE)
    out = format_results(r)
    assert out["period"] == "600.1" and out["period_resp"] == "600.5"
    assert out["freq"] == "0.001666" and out["freq_resp"] == "0.001665"


def test_missing_response_values_show_a_dash():
    r = SimpleNamespace(period_t=600.0, period_t_resp=None, frequency_f=0.001667,
                        frequency_f_resp=None, **_BASE)
    out = format_results(r)
    assert out["period_resp"] == "—" and out["freq_resp"] == "—"
