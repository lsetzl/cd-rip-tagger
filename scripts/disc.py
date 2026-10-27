"""光学ドライブの検出と、cyanrip によるディスク情報取得・WAVリッピング。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

RIP_SUBDIR = "rip"

_PS_LIST_DRIVES = (
    "Get-CimInstance Win32_CDROMDrive | "
    "Select-Object -Property Drive,Caption | ConvertTo-Json -Compress"
)

_TRACK_HEAD_RE = re.compile(r"^\s*Track\s+(\d+)\b", re.IGNORECASE)
_DURATION_RE = re.compile(r"(?:duration|length|time)\s*[:=]\s*([0-9]+:[0-9]{2}(?:\.[0-9]+)?)", re.IGNORECASE)
_TIME_RE = re.compile(r"\b([0-9]+:[0-9]{2}(?:\.[0-9]+)?)\b")
_TRACK_COUNT_RE = re.compile(r"(?:number of tracks|total tracks|tracks)\s*[:=]\s*(\d+)", re.IGNORECASE)


def list_drives() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _PS_LIST_DRIVES,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"光学ドライブの一覧取得に失敗しました: {exc}") from exc
    output = completed.stdout.strip()
    if not output:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ドライブ一覧の解析に失敗しました: {output!r}") from exc
    if isinstance(data, dict):
        data = [data]
    drives = []
    for item in data:
        letter = (item.get("Drive") or "").strip()
        if letter:
            drives.append({"drive": letter, "caption": (item.get("Caption") or "").strip()})
    return drives


def resolve_drive(explicit: str | None) -> tuple[str | None, list[dict[str, str]]]:
    drives = list_drives()
    if explicit:
        letter = explicit if explicit.endswith(":") else f"{explicit}:"
        return letter.upper(), drives
    if len(drives) == 1:
        return drives[0]["drive"], drives
    return None, drives


def parse_disc_info(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    tracks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        head = _TRACK_HEAD_RE.match(line)
        if head:
            current = {"number": int(head.group(1)), "duration": None}
            tracks.append(current)
        if current is not None and current["duration"] is None:
            if re.match(r"^\s*total\b", line, re.IGNORECASE):
                continue
            match = _DURATION_RE.search(line) or (_TIME_RE.search(line) if head else None)
            if match:
                current["duration"] = match.group(1)

    declared = None
    for line in lines:
        match = _TRACK_COUNT_RE.search(line)
        if match:
            declared = int(match.group(1))
            break

    track_count = declared if declared is not None else len(tracks)
    return {
        "track_count": track_count,
        "tracks": tracks,
        "declared_track_count": declared,
        "parse_confident": bool(tracks) and track_count == len(tracks),
    }


def probe(cyanrip: str, drive: str) -> dict[str, Any]:
    cmd = [cyanrip, "-d", drive, "-I", "-N", "-A", "-B", "-U"]
    completed = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=180)
    text = completed.stdout + ("\n" + completed.stderr if completed.stderr else "")
    if completed.returncode != 0 and not text.strip():
        raise RuntimeError(f"cyanrip -I が失敗しました（終了コード {completed.returncode}）")
    info = parse_disc_info(text)
    info.update({"drive": drive, "exit_code": completed.returncode, "raw": text})
    return info


def collect_ripped_wavs(workdir: Path) -> dict[int, Path]:
    rip_dir = workdir / RIP_SUBDIR
    search_root = rip_dir if rip_dir.is_dir() else workdir
    found: dict[int, Path] = {}
    for wav in sorted(search_root.rglob("*.wav")):
        match = re.search(r"(\d+)", wav.stem)
        if match is None:
            continue
        found[int(match.group(1))] = wav
    return found


def rip_to_wav(cyanrip: str, drive: str, workdir: Path) -> dict[int, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        cyanrip,
        "-d",
        drive,
        "-N",  # MusicBrainz検索を行わず、メタデータ無しでも続行する
        "-A",
        "-B",
        "-U",  # AccurateRip / AcoustID / カバーアートDB への問い合わせを止める
        "-G",
        "-K",
        "-o",
        "wav",
        "-D",
        RIP_SUBDIR,
        "-F",
        "{track}",
    ]
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    completed = subprocess.run(cmd, cwd=str(workdir))
    wavs = collect_ripped_wavs(workdir)
    if not wavs:
        raise RuntimeError(
            f"リッピング結果のWAVが見つかりませんでした（cyanrip 終了コード {completed.returncode}）。"
        )
    return wavs
