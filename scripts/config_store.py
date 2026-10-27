"""設定ファイル（ライブラリルート・エンコード品質）の読み書き。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "cd-rip-tagger"

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "v0": {
        "label": "VBR V0（最高品質・約245kbps）",
        "ffmpeg_args": ["-q:a", "0"],
    },
    "v2": {
        "label": "VBR V2（推奨・約190kbps）",
        "ffmpeg_args": ["-q:a", "2"],
    },
    "cbr320": {
        "label": "CBR 320kbps（固定ビットレート）",
        "ffmpeg_args": ["-b:a", "320k"],
    },
}

DEFAULT_QUALITY = "v2"


def config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def bin_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / APP_NAME / "bin"


def load() -> dict[str, Any] | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"設定ファイルを読めませんでした: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"設定ファイルの形式が不正です: {path}")
    return data


def save(library_root: str, quality: str, drive_offset: int = 0) -> dict[str, Any]:
    if quality not in QUALITY_PRESETS:
        raise ValueError(f"未知の品質設定です: {quality}（選択肢: {', '.join(QUALITY_PRESETS)}）")
    root = Path(library_root).expanduser()
    data = {
        "library_root": str(root),
        "quality": quality,
        "drive_offset": int(drive_offset),
        "version": 1,
    }
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return data


def require() -> dict[str, Any]:
    data = load()
    if data is None:
        raise RuntimeError(
            "設定がまだありません。`setup --library-root <パス> --quality <v0|v2|cbr320>` を実行してください。"
        )
    missing = [key for key in ("library_root", "quality") if not data.get(key)]
    if missing:
        raise RuntimeError(f"設定が不完全です（{', '.join(missing)}）。`setup --reconfigure` を実行してください。")
    if data["quality"] not in QUALITY_PRESETS:
        raise RuntimeError(f"設定の品質が未知の値です: {data['quality']}")
    return data


def ffmpeg_args(quality: str) -> list[str]:
    return list(QUALITY_PRESETS[quality]["ffmpeg_args"])
