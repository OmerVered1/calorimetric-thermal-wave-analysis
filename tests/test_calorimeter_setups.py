import json

import pytest

from calorimeter_setups import CalorimeterSetup, SetupStore


def test_setup_roundtrips_through_dict():
    s = CalorimeterSetup(
        name="Drop @ bench",
        calorimeter="Drop (Alexsys)",
        profile_name="Alexsys Drop",
        host="192.168.1.50",
        interface=r"\Device\NPF_{ABC}",
        port=1210,
        notes="argon, 800C",
    )
    assert CalorimeterSetup.from_dict(s.to_dict()) == s


def test_from_dict_tolerates_missing_optional_fields():
    s = CalorimeterSetup.from_dict(
        {"name": "n", "calorimeter": "Drop (Alexsys)", "profile_name": "Alexsys Drop"}
    )
    assert s.host == ""
    assert s.interface == ""
    assert s.port == 1210


def test_from_dict_requires_a_name():
    with pytest.raises(ValueError):
        CalorimeterSetup.from_dict({"calorimeter": "x", "profile_name": "y"})


def test_store_saves_and_reloads(tmp_path):
    path = tmp_path / "setups.json"
    store = SetupStore(path)
    s = CalorimeterSetup("A", "Drop (Alexsys)", "Alexsys Drop", host="10.0.0.1")
    store.save(s)

    reloaded = SetupStore(path)
    assert reloaded.names() == ["A"]
    assert reloaded.get("A").host == "10.0.0.1"


def test_store_names_are_sorted_case_insensitively(tmp_path):
    store = SetupStore(tmp_path / "s.json")
    for n in ("beta", "Alpha", "gamma"):
        store.save(CalorimeterSetup(n, "c", "p"))
    assert store.names() == ["Alpha", "beta", "gamma"]


def test_saving_same_name_replaces(tmp_path):
    store = SetupStore(tmp_path / "s.json")
    store.save(CalorimeterSetup("A", "c", "p", host="1.1.1.1"))
    store.save(CalorimeterSetup("A", "c", "p", host="2.2.2.2"))
    assert store.names() == ["A"]
    assert store.get("A").host == "2.2.2.2"


def test_delete_and_rename(tmp_path):
    store = SetupStore(tmp_path / "s.json")
    store.save(CalorimeterSetup("A", "c", "p"))
    assert store.rename("A", "B") is True
    assert store.names() == ["B"]
    store.delete("B")
    assert store.names() == []


def test_rename_onto_existing_name_is_refused(tmp_path):
    store = SetupStore(tmp_path / "s.json")
    store.save(CalorimeterSetup("A", "c", "p"))
    store.save(CalorimeterSetup("B", "c", "p"))
    assert store.rename("A", "B") is False
    assert store.names() == ["A", "B"]


def test_corrupt_file_does_not_raise(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{ this is not json", encoding="utf-8")
    # A hand-edited or truncated file must not stop the app from starting.
    assert SetupStore(path).names() == []


def test_unreadable_entries_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps({"setups": [{"no_name": 1}, {"name": "ok", "calorimeter": "c",
                                                "profile_name": "p"}]}),
        encoding="utf-8",
    )
    assert SetupStore(path).names() == ["ok"]


def test_store_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "s.json"
    store = SetupStore(path)
    store.save(CalorimeterSetup("A", "c", "p"))
    assert path.is_file()
