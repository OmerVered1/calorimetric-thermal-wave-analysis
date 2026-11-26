"""The results column of the Analysis tab: numbers, the check-the-cycle warning, errors."""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QGridLayout, QWidget

from ctwa import theme
from ctwa.analysis.jsmath import js_to_precision
from ctwa.analysis.types import AnalysisResults

DASH = "—"

# The webapp's English texts (lib/i18n/en.ts) for each PipelineError code.
PIPELINE_MESSAGES = {
    "parseFailed": "Could not parse one or both files. Check the file format.",
    "notEnoughOverlap": "Not enough overlapping data after clock synchronisation. Check start times.",
    "tooFewPoints": "Selected region has too few data points. Widen the selection range.",
    "smoothFailed": "Could not fit a sine to the selected region — widen it or check the signal.",
}
CRASH_MESSAGE = "The analysis process stopped unexpectedly; press Analyze to try again."
LOAD_CRASH_MESSAGE = "The analysis process stopped unexpectedly; open the run again."
NOT_CAPTURE_MESSAGE = "This file isn't a CTWA/C80 one-file capture."
EDGE_WARNING = ("The lag is right at the edge of a period. If the response really lags by about a "
                "full period more, or the two clocks are off, this value is wrong: check it "
                "against the chart.")
SE_SOURCES = {"blocks": "from the scatter between cycles",
              "pairs": "half the difference between the two pairs",
              "formal": "from the fit residuals; optimistic with few cycles"}

ROWS = [  # key, label (lib/i18n/en.ts), unit
    ("alpha_phase_raw", "\u03b1 Phase (Raw)", "mm\u00b2/s"),
    ("alpha_phase_cal", "\u03b1 Phase (Calibrated)", "mm\u00b2/s"),
    ("alpha_combined_raw", "\u03b1 Combined (Raw)", "mm\u00b2/s"),
    ("alpha_combined_cal", "\u03b1 Combined (Calibrated)", "mm\u00b2/s"),
    ("lag", "Net Time Lag \u00b1 standard error", "s"),
    ("a1", "Amplitude A\u2081", "mW"),
    ("a2", "Amplitude A\u2082", "mW"),
    ("period", "Source Period T", "s"),
    ("period_resp", "Response Period T", "s"),
    ("freq", "Source Frequency f", "Hz"),
    ("freq_resp", "Response Frequency f", "Hz"),
    ("ln_term", "ln(A\u2081\u221ar\u2081 / A\u2082\u221ar\u2082)", ""),
]


def _prec(x: Optional[float], digits: int, scale: float = 1.0) -> str:
    if x is None or x != x:
        return DASH
    return js_to_precision(x * scale, digits)


def format_results(r: AnalysisResults) -> Dict[str, str]:
    lag = DASH if r.net_lag_dt is None or r.net_lag_dt != r.net_lag_dt else "%.1f" % r.net_lag_dt
    if lag != DASH and r.lag_se is not None and r.lag_se == r.lag_se:
        lag += " ± %.1f" % r.lag_se
    return {
        "alpha_phase_raw": _prec(r.alpha_phase_raw, 4, 1e6),
        "alpha_phase_cal": _prec(r.alpha_phase_cal, 4, 1e6),
        "alpha_combined_raw": _prec(r.alpha_combined_raw, 4, 1e6),
        "alpha_combined_cal": _prec(r.alpha_combined_cal, 4, 1e6),
        "lag": lag,
        "a1": _prec(r.amplitude_a1, 3),
        "a2": _prec(r.amplitude_a2, 3),
        "period": _prec(r.period_t, 4),
        "period_resp": _prec(r.period_t_resp, 4),
        "freq": _prec(r.frequency_f, 4),
        "freq_resp": _prec(r.frequency_f_resp, 4),
        "ln_term": _prec(r.ln_term, 4),
    }


class ResultsPanel(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        theme.set_role(self, "card")
        lay = QVBoxLayout(self)
        lay.addWidget(theme.set_role(QLabel("Results"), "section"))
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.hide()
        lay.addWidget(self._message)
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setVerticalSpacing(2)
        lay.addLayout(grid)
        self._values: Dict[str, QLabel] = {}
        for i, (key, label, unit) in enumerate(ROWS):
            grid.addWidget(theme.set_role(QLabel(label), "stat-label"), i, 0)
            v = theme.set_role(QLabel(DASH), "stat-value")
            v.setFont(theme.numeric_font(theme.TEXT))
            grid.addWidget(v, i, 1)
            self._values[key] = v
            grid.addWidget(theme.set_role(QLabel(unit), "faint"), i, 2)
        self._note = theme.set_role(QLabel(), "faint")
        self._note.setWordWrap(True)
        lay.addWidget(self._note)
        self._warning = theme.set_role(QLabel(), "pill", tone="warn")
        self._warning.setWordWrap(True)
        self._warning.hide()
        lay.addWidget(self._warning)
        lay.addStretch(1)

    # ---- reading (tests, and Task 8) ----
    def text(self, key: str) -> str:
        return self._values[key].text()

    def message(self) -> str:
        return self._message.text()

    def warning_visible(self) -> bool:
        return not self._warning.isHidden()

    # ---- showing ----
    def clear(self) -> None:
        self._message.hide()
        self._message.setText("")
        self._warning.hide()
        self._note.setText("")
        for v in self._values.values():
            v.setText(DASH)

    def show_error(self, kind: str, message: str, during_load: bool = False) -> None:
        self.clear()
        if kind == "pipeline":
            # a parse failure while opening means the file is not a one-file capture
            text = (NOT_CAPTURE_MESSAGE if during_load and message == "parseFailed"
                    else PIPELINE_MESSAGES.get(message, message))
        elif kind == "crash":
            text = LOAD_CRASH_MESSAGE if during_load else CRASH_MESSAGE
        else:
            text = message
        theme.set_role(self._message, "danger")
        self._message.setText(text)
        self._message.show()

    def show_stale(self) -> None:
        """The settings moved on: the numbers stay, with a note that they are old."""
        theme.set_role(self._message, "muted")
        self._message.setText("Settings changed since this result; press Analyze.")
        self._message.show()

    def show_note(self, text: str) -> None:
        self.clear()
        theme.set_role(self._message, "muted")
        self._message.setText(text)
        self._message.show()

    def show_busy(self) -> None:
        self.clear()
        theme.set_role(self._message, "muted")
        self._message.setText("Analyzing…")
        self._message.show()

    def show_results(self, r: AnalysisResults) -> None:
        self.clear()
        for key, text in format_results(r).items():
            self._values[key].setText(text)
        notes = []
        if r.lag_se is not None and r.lag_se_source:
            notes.append("Lag standard error: %s" % SE_SOURCES.get(r.lag_se_source, r.lag_se_source))
        if r.lag_cycles:
            notes.append("includes %d whole period(s)" % r.lag_cycles)
        self._note.setText(" \u00b7 ".join(notes))
        if r.lag_near_edge:
            self._warning.setText(EDGE_WARNING)
            self._warning.show()
