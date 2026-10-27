"""依存の自動取得が、失敗を JSON で返せる形の例外に変換することを確かめる。"""
import zipfile

import deps
import pytest


def test_pip_failure_becomes_runtime_error(monkeypatch):
    class Completed:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not find a version that satisfies the requirement mutagen\n"

    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: Completed())
    # CalledProcessError のままだと main() の except を抜けてトレースバックになる
    with pytest.raises(RuntimeError, match="pip install mutagen が失敗"):
        deps._install_mutagen()


def test_pip_success_returns_interpreter(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "Successfully installed mutagen-1.48.1"
        stderr = ""

    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: Completed())
    assert deps._install_mutagen() == deps.sys.executable


def test_broken_zip_becomes_runtime_error(monkeypatch, tmp_path):
    monkeypatch.setattr(deps.config_store, "bin_dir", lambda: tmp_path / "bin")

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not a zip")

    monkeypatch.setattr(deps, "_download", fake_download)
    with pytest.raises(RuntimeError, match="zipが壊れています"):
        deps._install_ffmpeg()


def test_zip_without_ffmpeg_exe_becomes_runtime_error(monkeypatch, tmp_path):
    monkeypatch.setattr(deps.config_store, "bin_dir", lambda: tmp_path / "bin")

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("readme.txt", "no exe here")

    monkeypatch.setattr(deps, "_download", fake_download)
    with pytest.raises(RuntimeError, match="ffmpeg.exe が見つかりませんでした"):
        deps._install_ffmpeg()


def test_install_rejects_unknown_dependency():
    with pytest.raises(ValueError, match="未知の依存"):
        deps.install(["nonexistent"])
