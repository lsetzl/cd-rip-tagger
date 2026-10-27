"""中間ファイル（可逆圧縮）から MP3 へのエンコード。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import config_store


def encode(ffmpeg: str, source: Path, mp3: Path, quality: str) -> None:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        *config_store.ffmpeg_args(quality),
        "-write_id3v1",
        "0",
        str(mp3),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffmpeg でのエンコードに失敗しました: {source.name}\n{completed.stderr.strip()}"
        )
