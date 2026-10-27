"""ID3タグの書き込みとジャケット画像の取得。

日本語が化けにくい ID3v2.3 + UTF-16 で書き、ID3v1 は書かない。
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

UTF16 = 1
LATIN1 = 0
FRONT_COVER = 3
MAX_COVER_BYTES = 8 * 1024 * 1024


def fetch_cover(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "cd-rip-tagger"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = response.read(MAX_COVER_BYTES + 1)
    if len(data) > MAX_COVER_BYTES:
        raise RuntimeError(f"ジャケット画像が大きすぎます（{MAX_COVER_BYTES}バイト超）: {url}")
    mime = detect_mime(data, content_type)
    if mime is None:
        raise RuntimeError(f"画像として扱えないデータでした（Content-Type: {content_type or '不明'}）: {url}")
    return {"mime": mime, "data": data, "url": url}


def detect_mime(data: bytes, content_type: str = "") -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content_type in ("image/jpeg", "image/png"):
        return content_type
    return None


def write_tags(
    mp3_path: Path,
    *,
    album: str | None,
    album_artist: str | None,
    title: str | None,
    track: int,
    total_tracks: int,
    artist: str | None = None,
    year: str | None = None,
    cover: dict[str, Any] | None = None,
) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK

    tags = ID3()
    if album:
        tags.add(TALB(encoding=UTF16, text=[album]))
    if album_artist:
        tags.add(TPE2(encoding=UTF16, text=[album_artist]))
    if title:
        tags.add(TIT2(encoding=UTF16, text=[title]))
    tags.add(TRCK(encoding=LATIN1, text=[f"{track}/{total_tracks}"]))
    # 曲ごとのアーティストが無ければアルバムアーティストで埋める（空欄だと表示が崩れるプレイヤーがある）
    effective_artist = artist or album_artist
    if effective_artist:
        tags.add(TPE1(encoding=UTF16, text=[effective_artist]))
    if year:
        tags.add(TDRC(encoding=LATIN1, text=[str(year)]))
    if cover:
        tags.add(
            APIC(
                encoding=LATIN1,
                mime=cover["mime"],
                type=FRONT_COVER,
                desc="",
                data=cover["data"],
            )
        )
    tags.update_to_v23()
    tags.save(str(mp3_path), v2_version=3, v1=0)
