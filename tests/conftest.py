"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _runs_save_to_a_scratch_folder(tmp_path_factory, monkeypatch):
    """Every sweep streams a CSV into the save folder, auto-save on or off.
    Without this the suite wrote its simulated runs into the user's real data
    folder (~/Documents/K2602B_Data), next to measurements."""
    import ctwa.app
    monkeypatch.setattr(ctwa.app, "DEFAULT_SAVE_DIR", str(tmp_path_factory.mktemp("runs")))
