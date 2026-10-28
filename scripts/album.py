"""アルバム情報JSONの検証と、出力計画（確認画面の中身）の組み立て。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import naming


def load(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"アルバム情報JSONを解析できませんでした: {path} ({exc})") from exc
    return validate(data)


def validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise RuntimeError("アルバム情報JSONはオブジェクトである必要があります。")
    for key in ("album", "album_artist"):
        if not str(data.get(key) or "").strip():
            raise RuntimeError(f"アルバム情報JSONに必須項目 {key} がありません。")
    raw_tracks = data.get("tracks")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise RuntimeError("アルバム情報JSONの tracks が空です。")

    tracks = []
    for index, item in enumerate(raw_tracks, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"tracks[{index - 1}] がオブジェクトではありません。")
        number = item.get("number", index)
        try:
            number = int(number)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"tracks[{index - 1}] の number が整数ではありません: {number!r}") from exc
        if number < 1:
            raise RuntimeError(f"tracks[{index - 1}] の number が1未満です: {number}")
        title = str(item.get("title") or "").strip()
        if not title:
            raise RuntimeError(f"tracks[{index - 1}]（number={number}）に title がありません。")
        artist = str(item.get("artist") or "").strip() or None
        source_track = item.get("source_track", number)
        try:
            source_track = int(source_track)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"tracks[{index - 1}] の source_track が整数ではありません: {source_track!r}"
            ) from exc
        if source_track < 1:
            raise RuntimeError(
                f"tracks[{index - 1}]（number={number}）の source_track が1未満です: {source_track}"
            )
        tracks.append(
            {
                "number": number,
                "title": title,
                "artist": artist,
                "source_track": source_track,
            }
        )

    tracks.sort(key=lambda track: track["number"])
    return {
        "album": str(data["album"]).strip(),
        "album_artist": str(data["album_artist"]).strip(),
        "year": str(data.get("year") or "").strip() or None,
        "cover_url": str(data.get("cover_url") or "").strip() or None,
        "source_url": str(data.get("source_url") or "").strip() or None,
        "tracks": tracks,
    }


def build_plan(
    album: dict[str, Any],
    config: dict[str, Any],
    *,
    disc_track_count: int | None = None,
) -> dict[str, Any]:
    out_dir = naming.album_dir(config["library_root"], album["album_artist"], album["album"])
    total = len(album["tracks"])
    files = []
    for track in album["tracks"]:
        filename = naming.track_filename(track["number"], track["title"])
        files.append(
            {
                "number": track["number"],
                "source_track": track["source_track"],
                "title": track["title"],
                "artist": track["artist"] or album["album_artist"],
                "artist_is_fallback": track["artist"] is None,
                "filename": filename,
                "path": str(out_dir / filename),
                "exists": (out_dir / filename).exists(),
            }
        )

    # CDに無いトラックを指していたら、リッピングで必ず失敗する。確認画面に進む前に止める
    if disc_track_count is not None:
        out_of_range = sorted(
            {file["source_track"] for file in files if file["source_track"] > disc_track_count}
        )
        if out_of_range:
            raise RuntimeError(
                f"source_track がCDのトラック数（{disc_track_count}）を超えています: "
                f"{out_of_range}。取り込めないので、対応付けを直してください。"
            )

    warnings: list[str] = []
    numbers = [track["number"] for track in album["tracks"]]
    if len(set(numbers)) != len(numbers):
        warnings.append("トラック番号が重複しています。")
    if numbers and numbers != list(range(1, total + 1)):
        warnings.append(f"トラック番号が1〜{total}の連番になっていません: {numbers}")
    if disc_track_count is not None and disc_track_count != total:
        warnings.append(
            f"CDのトラック数（{disc_track_count}）とページの曲数（{total}）が一致しません。"
            "どのトラックをどの曲に対応させるか指示してください。"
        )
    if not album["year"]:
        warnings.append("年（頒布日・発売日）がページから取れていないため、年タグは空になります。")
    if not album["cover_url"]:
        warnings.append("ジャケット画像のURLが無いため、画像は埋め込まれません。")
    missing_artist = [file["number"] for file in files if file["artist_is_fallback"]]
    if missing_artist:
        warnings.append(
            f"曲ごとのアーティストが無いトラックはアルバムアーティストで埋めます: {missing_artist}"
        )
    remapped = [
        f'{file["number"]}←CD{file["source_track"]}'
        for file in files
        if file["source_track"] != file["number"]
    ]
    if remapped:
        warnings.append(f"CDのトラックを読み替えて取り込みます: {', '.join(remapped)}")
    existing = [file["path"] for file in files if file["exists"]]
    if existing:
        warnings.append(f"同名ファイルが既に{len(existing)}件あります。実行すると上書きされます。")
    warnings.extend(naming.path_warnings([Path(file["path"]) for file in files]))

    return {
        "library_root": config["library_root"],
        "quality": config["quality"],
        "output_dir": str(out_dir),
        "album": album["album"],
        "album_artist": album["album_artist"],
        "year": album["year"],
        "cover_url": album["cover_url"],
        "source_url": album["source_url"],
        "total_tracks": total,
        "disc_track_count": disc_track_count,
        "files": files,
        "existing_files": existing,
        "warnings": warnings,
    }
