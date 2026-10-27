import config_store
import pytest


def test_paths_follow_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert config_store.config_path() == tmp_path / "roaming" / "cd-rip-tagger" / "config.json"
    assert config_store.bin_dir() == tmp_path / "local" / "cd-rip-tagger" / "bin"


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_store.save(r"D:\Music", "v0")
    loaded = config_store.load()
    assert loaded["library_root"] == r"D:\Music"
    assert loaded["quality"] == "v0"


def test_load_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config_store.load() is None


def test_require_raises_without_config(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(RuntimeError):
        config_store.require()


def test_save_rejects_unknown_quality(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(ValueError):
        config_store.save(r"D:\Music", "v9")


def test_quality_presets_map_to_ffmpeg_args():
    assert config_store.ffmpeg_args("v0") == ["-q:a", "0"]
    assert config_store.ffmpeg_args("v2") == ["-q:a", "2"]
    assert config_store.ffmpeg_args("cbr320") == ["-b:a", "320k"]


def test_drive_offset_defaults_to_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config_store.save(r"D:\Music", "v2")["drive_offset"] == 0


def test_drive_offset_is_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_store.save(r"D:\Music", "v2", 667)
    assert config_store.load()["drive_offset"] == 667
