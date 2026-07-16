import importlib
from pathlib import Path

import core.settings as settings


def _reload_with_config(monkeypatch, cfg_path: Path):
    # Redirect the settings file to a temp location for the test.
    monkeypatch.setenv("WEBINAR_RECORDER_CONFIG", str(cfg_path))
    importlib.reload(settings)
    return settings


def test_missing_file_returns_empty(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "nope.json")
    assert s.load_settings() == {}


def test_default_data_dir_used_when_unset(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    assert s.get_data_dir() == s.default_data_dir()


def test_set_and_get_data_dir_roundtrip(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    target = tmp_path / "OneDrive" / "Webinare"
    s.set_data_dir(target)
    # Fresh read (simulates next launch).
    assert s.get_data_dir() == Path(str(target))
    assert (tmp_path / "settings.json").exists()


def test_last_session_none_when_unset(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    assert s.get_last_session() is None


def test_last_session_roundtrip_when_folder_exists(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    webinar = tmp_path / "Webinar_A"
    webinar.mkdir()
    s.set_last_session(webinar)
    assert s.get_last_session() == webinar


def test_last_session_ignored_when_folder_gone(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_last_session(tmp_path / "deleted_webinar")  # never created
    assert s.get_last_session() is None


def test_corrupt_file_falls_back_to_empty(monkeypatch, tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text("{ not valid json", encoding="utf-8")
    s = _reload_with_config(monkeypatch, cfg)
    assert s.load_settings() == {}
    assert s.get_data_dir() == s.default_data_dir()


def test_other_keys_preserved_when_setting_data_dir(monkeypatch, tmp_path):
    cfg = tmp_path / "settings.json"
    s = _reload_with_config(monkeypatch, cfg)
    s.save_settings({"foo": "bar"})
    s.set_data_dir(tmp_path / "x")
    assert s.load_settings()["foo"] == "bar"


def test_work_area_geometry_unset_returns_none(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    assert s.get_work_area_geometry() is None


def test_work_area_geometry_roundtrip(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_work_area_geometry(100, 200, 640, 480)
    assert s.get_work_area_geometry() == (100, 200, 640, 480)


def test_work_area_geometry_independent_of_data_dir(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_data_dir(tmp_path / "data")
    s.set_work_area_geometry(10, 20, 300, 400)
    assert s.get_work_area_geometry() == (10, 20, 300, 400)
    assert s.get_data_dir() == Path(str(tmp_path / "data"))


def test_player_volumes_default(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    assert s.get_player_volumes() == (100, 100)


def test_player_volumes_roundtrip(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_player_volumes(70, 45)
    assert s.get_player_volumes() == (70, 45)


def test_player_volumes_clamped(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_player_volumes(250, -30)
    assert s.get_player_volumes() == (100, 0)


def test_player_volumes_independent_of_other_settings(monkeypatch, tmp_path):
    s = _reload_with_config(monkeypatch, tmp_path / "settings.json")
    s.set_mic_device("Mikrofon (Logitech)")
    s.set_player_volumes(80, 60)
    assert s.get_player_volumes() == (80, 60)
    assert s.get_mic_device() == "Mikrofon (Logitech)"
