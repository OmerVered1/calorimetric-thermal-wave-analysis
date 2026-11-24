"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _runs_save_to_a_scratch_folder(tmp_path_factory, monkeypatch):
    """Every sweep streams a CSV into the save folder, auto-save on or off.
    Without this the suite wrote its simulated runs into the user's real data
    folder (~/Documents/K2602B_Data), next to measurements."""
    import ctwa.app
    monkeypatch.setattr(ctwa.app, "DEFAULT_SAVE_DIR", str(tmp_path_factory.mktemp("runs")))


@pytest.fixture(autouse=True)
def _no_real_cloud(tmp_path_factory, monkeypatch):
    """A MainWindow never talks to the internet, reads the OS keyring or uses the
    user's upload queue in tests: it gets an offline client and a scratch queue."""
    import ctwa.app
    from ctwa.cloud.client import Offline
    from ctwa.cloud.queue import UploadQueue

    class OfflineClient:
        def select(self, *a, **k):
            raise Offline("tests are offline")
        insert = update = select

    folder = str(tmp_path_factory.mktemp("queue"))
    monkeypatch.setattr(ctwa.app, "_make_cloud_services",
                        lambda: (OfflineClient(), UploadQueue(folder)))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: takes seconds, not milliseconds (speed checks)")
