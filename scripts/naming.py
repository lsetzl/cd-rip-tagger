"""出力先パスとファイル名の組み立て。"""
from __future__ import annotations

import re
from pathlib import Path

# Windows のパスに使えない文字を全角の同等文字へ置き換える
INVALID_CHAR_MAP = {
    "\\": "＼",
    "/": "／",
    ":": "：",
    "*": "＊",
    "?": "？",
    '"': "＂",
    "<": "＜",
    ">": "＞",
    "|": "｜",
}

RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_PATH = 260


def sanitize_component(name: str | None, fallback: str = "_") -> str:
    text = "".join(INVALID_CHAR_MAP.get(ch, ch) for ch in (name or ""))
    text = "".join(" " if ord(ch) < 0x20 or ord(ch) == 0x7F else ch for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(" .")
    if not text:
        return fallback
    if text.split(".")[0].upper() in RESERVED_NAMES:
        text = f"_{text}"
    return text


def album_dir(library_root: str | Path, album_artist: str | None, album: str | None) -> Path:
    return (
        Path(library_root)
        / sanitize_component(album_artist, "Unknown Artist")
        / sanitize_component(album, "Unknown Album")
    )


def track_filename(number: int, title: str | None, ext: str = ".mp3") -> str:
    return f"{number:02d} {sanitize_component(title, f'Track {number:02d}')}{ext}"


def path_warnings(paths: list[Path]) -> list[str]:
    warnings = []
    for path in paths:
        length = len(str(path))
        if length >= MAX_PATH:
            warnings.append(f"パスが{MAX_PATH}文字以上（{length}文字）です: {path}")
    return warnings
