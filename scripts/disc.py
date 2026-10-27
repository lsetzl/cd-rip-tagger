"""光学ドライブの検出と、cyanrip によるディスク情報取得・WAVリッピング。"""
from __future__ import annotations

import ctypes
import functools
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

SM_REMOTESESSION = 0x1000

FRAMES_PER_SECOND = 75
CDA_STUB_SIZE = 44

RIP_SUBDIR = "rip"

# 0.9.3 にもあるフラグ。MusicBrainz・AccurateRip・カバーアートDBへの問い合わせを止める
BASE_FLAGS = ["-N", "-A", "-U"]
# cyanrip のバージョンによって有無が変わるフラグ（-B は AcoustID 無効化、master のみ）
OPTIONAL_FLAGS = ["B"]

_HELP_FLAG_RE = re.compile(r"^\s+-([A-Za-z])\b")
_FORMAT_RE = re.compile(r"^\s+(\w+)\s+folder:.*?extension:\s*(\w+)", re.MULTILINE)

# 中間ファイルは可逆圧縮のものを使う（この順で最初に対応しているものを選ぶ）
LOSSLESS_PREFERENCE = ["flac", "wavpack", "alac", "tta"]

_TOC_FAILURE_RE = re.compile(r"could not read TOC|Invalid number of tracks", re.IGNORECASE)

def raw_access_context() -> dict[str, bool]:
    try:
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        elevated = False
    try:
        remote = bool(ctypes.windll.user32.GetSystemMetrics(SM_REMOTESESSION))
    except (AttributeError, OSError):
        remote = False
    return {"elevated": elevated, "remote_session": remote}


GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
ERROR_ACCESS_DENIED = 5


def raw_read_available(drive: str) -> dict[str, Any]:
    """生アクセス用にデバイスを開けるかを実際に試す（開いて即閉じるだけ）。

    権限レベルから推測するのではなく、できるかどうかを直接確かめる。管理者権限・
    セッション種別・デバイスのDACLのどれで許可されていても、同じように通る。
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        handle = kernel32.CreateFileW(
            f"\\\\.\\{drive}",
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
    except (AttributeError, OSError) as exc:
        return {"available": False, "win32_error": None, "detail": str(exc)}

    invalid = ctypes.c_void_p(-1).value
    if handle in (None, 0, invalid):
        return {"available": False, "win32_error": ctypes.get_last_error(), "detail": None}
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    return {"available": True, "win32_error": 0, "detail": None}


def access_denied_hint(context: dict[str, bool] | None = None) -> str:
    context = raw_access_context() if context is None else context
    lines = ["ディスクへの生アクセスが拒否されました。"]
    if context["remote_session"]:
        lines.append(
            "・リモートデスクトップ接続で実行されています。光学ドライブへのアクセスは"
            "コンソールセッションに割り当てられるため、リモートからは拒否されます。"
            "本体のコンソールから実行してください（コンソールなら管理者権限は不要です）。"
            "リモートのまま進めたい場合は、管理者として起動したセッションでなら通ります。"
        )
    elif not context["elevated"]:
        lines.append(
            "・管理者として起動したセッションでやり直すと通る場合があります。"
        )
    lines.append(
        "・ディスクが音楽CDであること、ドライブに正しく入っていること、"
        "他のソフトがドライブを占有していないことを確認してください。"
    )
    lines.append("（トラック数の取得と出力計画の確認は、生アクセスなしでも動きます。）")
    return "\n".join(lines)


TOC_FAILURE_HINT = "cyanrip がディスクの目次（TOC）を読めませんでした。"

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


@functools.lru_cache(maxsize=4)
def supported_flags(cyanrip: str) -> frozenset[str]:
    try:
        completed = subprocess.run(
            [cyanrip, "-h"], capture_output=True, text=True, errors="replace", timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    text = completed.stdout + completed.stderr
    return frozenset(
        match.group(1)
        for match in (_HELP_FLAG_RE.match(line) for line in text.splitlines())
        if match
    )


def optional_flags(cyanrip: str) -> list[str]:
    available = supported_flags(cyanrip)
    return [f"-{flag}" for flag in OPTIONAL_FLAGS if flag in available]


def build_probe_command(cyanrip: str, drive: str) -> list[str]:
    return [cyanrip, "-d", drive, "-I", *BASE_FLAGS, *optional_flags(cyanrip)]


@functools.lru_cache(maxsize=4)
def supported_formats(cyanrip: str) -> dict[str, str]:
    """`-o help` の出力から、対応する出力形式と拡張子を読む。

    リリース版 0.9.3 には wav / pcm が無く、GitHub の README（master）とは中身が違う。
    形式名を決め打ちにせず、実バイナリに聞く。
    """
    try:
        completed = subprocess.run(
            [cyanrip, "-o", "help"], capture_output=True, text=True, errors="replace", timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    text = completed.stdout + completed.stderr
    return {
        match.group(1): match.group(2)
        for match in _FORMAT_RE.finditer(text)
    }


def pick_intermediate_format(cyanrip: str) -> tuple[str, str]:
    formats = supported_formats(cyanrip)
    for name in LOSSLESS_PREFERENCE:
        if name in formats:
            return name, formats[name]
    raise RuntimeError(
        "cyanrip が可逆圧縮の出力形式に対応していません"
        f"（対応: {', '.join(sorted(formats)) or '取得できませんでした'}）。"
    )


def build_rip_command(cyanrip: str, drive: str, fmt: str, offset: int = 0) -> list[str]:
    return [
        cyanrip,
        "-d",
        drive,
        # 省略すると cyanrip が "Offset is unset!" で止まる（-I のときは不要）
        "-s",
        str(offset),
        *BASE_FLAGS,
        *optional_flags(cyanrip),
        "-G",
        "-K",
        "-o",
        fmt,
        "-D",
        RIP_SUBDIR,
        "-F",
        "{track}",
    ]


def frames_to_duration(frames: int) -> str:
    seconds, remainder = divmod(frames, FRAMES_PER_SECOND)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}.{remainder:02d}"


def parse_cda_stub(data: bytes) -> dict[str, Any] | None:
    """音楽CDの各トラックに対応する44バイトの .cda スタブを読む。

    Windows はシェル上に Track01.cda のようなスタブを見せる。中身は RIFF CDDA
    ヘッダで、トラック番号と長さ（フレーム数）が入っている。生アクセスではないため
    管理者権限が不要。
    """
    if len(data) < CDA_STUB_SIZE or data[:4] != b"RIFF" or data[8:12] != b"CDDA":
        return None
    number = struct.unpack_from("<H", data, 22)[0]
    start_frame, length_frames = struct.unpack_from("<II", data, 28)
    if number < 1:
        return None
    return {
        "number": number,
        "duration": frames_to_duration(length_frames),
        "length_frames": length_frames,
        "start_frame": start_frame,
    }


def read_cda_stubs(drive: str) -> list[dict[str, Any]]:
    root = Path(f"{drive}/")
    try:
        stubs = sorted(root.glob("*.cda"))
    except OSError:
        return []
    tracks = []
    for stub in stubs:
        try:
            parsed = parse_cda_stub(stub.read_bytes())
        except OSError:
            continue
        if parsed is not None:
            tracks.append(parsed)
    tracks.sort(key=lambda track: track["number"])
    return tracks


def probe(drive: str, cyanrip: str | None = None) -> dict[str, Any]:
    tracks = read_cda_stubs(drive)
    if tracks:
        return {
            "drive": drive,
            "source": "cda",
            "track_count": len(tracks),
            "declared_track_count": len(tracks),
            "tracks": tracks,
            "parse_confident": True,
        }
    if cyanrip is None:
        raise RuntimeError(
            f"{drive} に音楽CDのトラックが見つかりませんでした。"
            "ディスクが入っているか、音楽CDであるかを確認してください。"
        )
    return probe_via_cyanrip(cyanrip, drive)


def probe_via_cyanrip(cyanrip: str, drive: str) -> dict[str, Any]:
    cmd = build_probe_command(cyanrip, drive)
    completed = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=180)
    text = completed.stdout + ("\n" + completed.stderr if completed.stderr else "")
    if completed.returncode != 0 and not text.strip():
        raise RuntimeError(f"cyanrip -I が失敗しました（終了コード {completed.returncode}）")
    info = parse_disc_info(text)
    info.update(
        {"drive": drive, "source": "cyanrip", "exit_code": completed.returncode, "raw": text}
    )
    if toc_failed(text):
        # TOC が読めないと「Invalid number of tracks: 255」のような値が出るので採用しない
        info.update(
            {
                "track_count": 0,
                "tracks": [],
                "declared_track_count": None,
                "parse_confident": False,
                "error": TOC_FAILURE_HINT + "\n" + access_denied_hint(),
            }
        )
    return info


def toc_failed(text: str) -> bool:
    return bool(_TOC_FAILURE_RE.search(text))


def collect_ripped_tracks(workdir: Path, ext: str) -> dict[int, Path]:
    rip_dir = workdir / RIP_SUBDIR
    search_root = rip_dir if rip_dir.is_dir() else workdir
    found: dict[int, Path] = {}
    for path in sorted(search_root.rglob(f"*.{ext}")):
        match = re.search(r"(\d+)", path.stem)
        if match is None:
            continue
        found[int(match.group(1))] = path
    return found


def rip_tracks(cyanrip: str, drive: str, workdir: Path, offset: int = 0) -> dict[int, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    fmt, ext = pick_intermediate_format(cyanrip)
    cmd = build_rip_command(cyanrip, drive, fmt, offset)
    print(f"$ {' '.join(cmd)}", file=sys.stderr)

    # 進捗はそのまま流しつつ、失敗時の診断に使えるよう控えを取る
    captured: list[str] = []
    process = subprocess.Popen(
        cmd,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        captured.append(line)
        print(line.rstrip(), file=sys.stderr)
    returncode = process.wait()

    tracks = collect_ripped_tracks(workdir, ext)
    if not tracks:
        output = "".join(captured)
        tail = "".join(captured[-15:]).strip() or "(出力なし)"
        message = (
            f"リッピングに失敗しました（cyanrip 終了コード {returncode}、中間形式 {fmt}）。\n"
            f"cyanrip の出力:\n{tail}"
        )
        if toc_failed(output):
            message += "\n" + access_denied_hint()
        raise RuntimeError(message)
    return tracks
