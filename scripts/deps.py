"""依存ツール（cyanrip / ffmpeg / mutagen）の確認と、承認を得た上での自動取得。"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import config_store

CYANRIP_URL = "https://github.com/cyanreg/cyanrip/releases/latest/download/cyanrip-win64.exe"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"

PLAN = {
    "cyanrip": {
        "what": "cyanrip（CDリッパー）の Windows 単一実行ファイル",
        "source": CYANRIP_URL,
        "dest": lambda: str(config_store.bin_dir() / "cyanrip.exe"),
        "size_hint": "約8MB",
    },
    "ffmpeg": {
        "what": "ffmpeg（MP3エンコード用、libmp3lame入りビルド）",
        "source": FFMPEG_URL,
        "dest": lambda: str(config_store.bin_dir() / "ffmpeg"),
        "size_hint": "約80MBのzipを展開",
    },
    "mutagen": {
        "what": "mutagen（ID3タグ書き込み用のPythonライブラリ）",
        "source": f"pip install mutagen（{sys.executable}）",
        "dest": lambda: "現在のPython環境",
        "size_hint": "約1MB",
    },
}


def _managed(name: str) -> Path | None:
    candidates = [
        config_store.bin_dir() / f"{name}.exe",
        config_store.bin_dir() / name / "bin" / f"{name}.exe",
        config_store.bin_dir() / name / f"{name}.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def find_tool(name: str) -> str | None:
    managed = _managed(name)
    if managed is not None:
        return str(managed)
    found = shutil.which(name)
    return found


def has_mutagen() -> bool:
    return importlib.util.find_spec("mutagen") is not None


def check() -> dict[str, Any]:
    result: dict[str, Any] = {"tools": {}, "missing": [], "python": sys.version.split()[0]}
    for name in ("cyanrip", "ffmpeg"):
        path = find_tool(name)
        result["tools"][name] = {"found": path is not None, "path": path}
        if path is None:
            result["missing"].append(name)
    result["tools"]["mutagen"] = {"found": has_mutagen(), "path": sys.executable}
    if not has_mutagen():
        result["missing"].append("mutagen")
    result["install_plan"] = [
        {
            "name": name,
            "what": PLAN[name]["what"],
            "source": PLAN[name]["source"],
            "dest": PLAN[name]["dest"](),
            "size_hint": PLAN[name]["size_hint"],
        }
        for name in result["missing"]
    ]
    result["ok"] = not result["missing"]
    return result


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "cd-rip-tagger"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


def _install_cyanrip() -> str:
    dest = config_store.bin_dir() / "cyanrip.exe"
    print(f"cyanrip を取得中: {CYANRIP_URL}", file=sys.stderr)
    _download(CYANRIP_URL, dest)
    return str(dest)


def _install_ffmpeg() -> str:
    target = config_store.bin_dir() / "ffmpeg"
    with tempfile.TemporaryDirectory() as tmpdir:
        archive = Path(tmpdir) / "ffmpeg.zip"
        print(f"ffmpeg を取得中: {FFMPEG_URL}", file=sys.stderr)
        _download(FFMPEG_URL, archive)
        extract_dir = Path(tmpdir) / "extract"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        exes = list(extract_dir.rglob("ffmpeg.exe"))
        if not exes:
            raise RuntimeError("ダウンロードしたzipに ffmpeg.exe が見つかりませんでした。")
        source_bin = exes[0].parent
        if target.exists():
            shutil.rmtree(target)
        (target / "bin").mkdir(parents=True, exist_ok=True)
        for item in source_bin.iterdir():
            if item.is_file():
                shutil.copy2(item, target / "bin" / item.name)
    return str(target / "bin" / "ffmpeg.exe")


def _install_mutagen() -> str:
    print("mutagen を pip で導入中", file=sys.stderr)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "mutagen"],
        check=True,
    )
    return sys.executable


INSTALLERS = {
    "cyanrip": _install_cyanrip,
    "ffmpeg": _install_ffmpeg,
    "mutagen": _install_mutagen,
}


def install(names: list[str]) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("自動取得は Windows ネイティブ環境でのみ対応しています。")
    unknown = [name for name in names if name not in INSTALLERS]
    if unknown:
        raise ValueError(f"未知の依存です: {', '.join(unknown)}")
    installed = {}
    for name in names:
        installed[name] = INSTALLERS[name]()
    return {"installed": installed, "check": check()}


def require_tools(*names: str) -> dict[str, str]:
    resolved = {}
    problems = []
    for name in names:
        if name == "mutagen":
            if not has_mutagen():
                problems.append("mutagen（Pythonライブラリ）")
            continue
        path = find_tool(name)
        if path is None:
            problems.append(name)
        else:
            resolved[name] = path
    if problems:
        raise RuntimeError(
            "依存ツールが見つかりません: "
            + ", ".join(problems)
            + "。`check-deps` で導入方法を確認し、`install-deps --accept <名前>` で取得してください。"
        )
    return resolved
