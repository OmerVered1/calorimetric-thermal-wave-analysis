"""The predecessor's saved profiles and setups must carry over, untouched."""

import json

import calorimeter_setups
import sniffer.profile as profile


def _point_app_data_at(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "_app_data_base", lambda: tmp_path)


def test_new_program_uses_its_own_folder(tmp_path, monkeypatch):
    _point_app_data_at(tmp_path, monkeypatch)
    assert "Calorimetric Thermal Wave Analysis Program" in str(profile.user_profile_dir())


def test_setups_saved_by_the_old_program_are_seeded(tmp_path, monkeypatch):
    _point_app_data_at(tmp_path, monkeypatch)
    legacy = calorimeter_setups.legacy_setups_path()
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"setups": [
        {"name": "Drop bench", "calorimeter": "Drop (Alexsys)", "profile_name": "Alexsys Drop"}
    ]}))
    store = calorimeter_setups.SetupStore()
    assert store.names() == ["Drop bench"]


def test_the_old_programs_file_is_never_written(tmp_path, monkeypatch):
    """Both programs stay installed; ours must not clobber its data."""
    _point_app_data_at(tmp_path, monkeypatch)
    legacy = calorimeter_setups.legacy_setups_path()
    legacy.parent.mkdir(parents=True)
    original = json.dumps({"setups": [{"name": "A", "calorimeter": "c", "profile_name": "p"}]})
    legacy.write_text(original)

    store = calorimeter_setups.SetupStore()
    store.save(calorimeter_setups.CalorimeterSetup("B", "c", "p"))
    assert legacy.read_text() == original


def test_seeding_happens_only_once(tmp_path, monkeypatch):
    _point_app_data_at(tmp_path, monkeypatch)
    legacy = calorimeter_setups.legacy_setups_path()
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"setups": [{"name": "A", "calorimeter": "c", "profile_name": "p"}]}))
    store = calorimeter_setups.SetupStore()
    store.delete("A")
    # A setup deliberately deleted here must not come back from the old file.
    assert calorimeter_setups.SetupStore().names() == []


def test_profiles_saved_by_the_old_program_are_loaded(tmp_path, monkeypatch):
    _point_app_data_at(tmp_path, monkeypatch)
    bundled = {p.name: p for p in profile.load_profiles()}["Alexsys Drop"]
    legacy_dir = profile.legacy_profile_dir()
    legacy_dir.mkdir(parents=True)
    bundled.notes = "fixed on the bench"
    bundled.save(legacy_dir / "drop.json")
    loaded = {p.name: p for p in profile.load_profiles()}
    assert loaded["Alexsys Drop"].notes == "fixed on the bench"
