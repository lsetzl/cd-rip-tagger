"""cd-rip-tagger の CLI。

サブコマンド:
  setup         設定（ライブラリルート・エンコード品質）の表示と保存
  check-deps    依存ツールの確認と、不足分の導入計画を出力
  install-deps  ユーザーの承認を得た依存を取得
  drives        光学ドライブの一覧
  probe         ディスク情報（トラック数・各トラック長）を取得
  plan          アルバム情報JSONから、確認用の出力計画を組み立てる
  run           リッピング→エンコード→タグ付け→配置を実行
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import album as album_mod
import config_store
import deps
import disc
import encode
import tagging


def emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def cmd_setup(args: argparse.Namespace) -> int:
    presets = {key: value["label"] for key, value in config_store.QUALITY_PRESETS.items()}
    if args.library_root or args.quality:
        current = config_store.load() or {}
        library_root = args.library_root or current.get("library_root")
        quality = args.quality or current.get("quality") or config_store.DEFAULT_QUALITY
        if not library_root:
            raise RuntimeError("--library-root を指定してください。")
        saved = config_store.save(library_root, quality)
        emit({"action": "saved", "config_path": str(config_store.config_path()), "config": saved})
        return 0

    current = config_store.load()
    emit(
        {
            "action": "show",
            "configured": current is not None,
            "config_path": str(config_store.config_path()),
            "config": current,
            "quality_presets": presets,
            "default_quality": config_store.DEFAULT_QUALITY,
        }
    )
    return 0


def cmd_check_deps(_args: argparse.Namespace) -> int:
    emit(deps.check())
    return 0


def cmd_install_deps(args: argparse.Namespace) -> int:
    names = [name.strip() for name in args.accept.split(",") if name.strip()]
    if not names:
        raise RuntimeError("--accept に取得を承認した依存名を指定してください（例: cyanrip,ffmpeg,mutagen）。")
    emit(deps.install(names))
    return 0


def cmd_drives(_args: argparse.Namespace) -> int:
    emit({"drives": disc.list_drives()})
    return 0


def _resolve_drive_or_fail(explicit: str | None) -> str:
    drive, drives = disc.resolve_drive(explicit)
    if drive is None:
        if not drives:
            raise RuntimeError("光学ドライブが見つかりませんでした。")
        listed = ", ".join(f"{item['drive']} ({item['caption']})" for item in drives)
        raise RuntimeError(f"光学ドライブが複数あります。--drive で指定してください: {listed}")
    return drive


def cmd_probe(args: argparse.Namespace) -> int:
    tools = deps.require_tools("cyanrip")
    drive = _resolve_drive_or_fail(args.drive)
    emit(disc.probe(tools["cyanrip"], drive))
    return 0


def _disc_track_count(args: argparse.Namespace) -> int | None:
    if args.disc_track_count is not None:
        return args.disc_track_count
    if args.no_probe:
        return None
    try:
        tools = deps.require_tools("cyanrip")
        drive = _resolve_drive_or_fail(args.drive)
    except RuntimeError as exc:
        log(f"ディスク情報は取得しませんでした: {exc}")
        return None
    info = disc.probe(tools["cyanrip"], drive)
    if not info["parse_confident"]:
        log("cyanrip -I の解析結果が不確実です。raw 出力を確認してください。")
    return info["track_count"] or None


def cmd_plan(args: argparse.Namespace) -> int:
    config = config_store.require()
    album = album_mod.load(args.input)
    plan = album_mod.build_plan(album, config, disc_track_count=_disc_track_count(args))
    plan["deps"] = deps.check()
    emit(plan)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = config_store.require()
    album = album_mod.load(args.input)

    if args.dry_run:
        plan = album_mod.build_plan(album, config, disc_track_count=_disc_track_count(args))
        plan["dry_run"] = True
        emit(plan)
        return 0

    tools = deps.require_tools("cyanrip", "ffmpeg", "mutagen")
    drive = _resolve_drive_or_fail(args.drive)
    info = disc.probe(tools["cyanrip"], drive)
    plan = album_mod.build_plan(album, config, disc_track_count=info["track_count"] or None)

    if plan["existing_files"] and not args.overwrite:
        raise RuntimeError(
            f"出力先に同名ファイルが{len(plan['existing_files'])}件あります。"
            "上書きしてよければ --overwrite を付けて実行してください。"
        )

    cover = None
    if album["cover_url"]:
        log(f"ジャケット画像を取得: {album['cover_url']}")
        cover = tagging.fetch_cover(album["cover_url"])

    workdir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="cd-rip-tagger-"))
    keep_workdir = bool(args.work_dir) or args.keep_work_dir
    out_dir = Path(plan["output_dir"])
    written: list[str] = []
    try:
        log(f"作業ディレクトリ: {workdir}")
        wavs = disc.rip_to_wav(tools["cyanrip"], drive, workdir)
        out_dir.mkdir(parents=True, exist_ok=True)
        total = plan["total_tracks"]
        for file in plan["files"]:
            source = wavs.get(file["source_track"])
            if source is None:
                raise RuntimeError(
                    f"CDトラック {file['source_track']} のWAVが見つかりません"
                    f"（取り込めたトラック: {sorted(wavs)}）。"
                )
            mp3_path = out_dir / file["filename"]
            log(f"[{file['number']}/{total}] エンコード: {file['filename']}")
            encode.encode(tools["ffmpeg"], source, mp3_path, config["quality"])
            tagging.write_tags(
                mp3_path,
                album=album["album"],
                album_artist=album["album_artist"],
                title=file["title"],
                track=file["number"],
                total_tracks=total,
                artist=file["artist"],
                year=album["year"],
                cover=cover,
            )
            written.append(str(mp3_path))
    finally:
        if keep_workdir:
            log(f"作業ディレクトリを残しました: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    emit(
        {
            "action": "completed",
            "output_dir": str(out_dir),
            "quality": config["quality"],
            "written": written,
            "cover_embedded": cover is not None,
            "warnings": plan["warnings"],
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rip_and_tag", description="CDの取り込みからタグ付け・配置まで")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="設定の表示と保存")
    setup.add_argument("--library-root")
    setup.add_argument("--quality", choices=sorted(config_store.QUALITY_PRESETS))
    setup.set_defaults(func=cmd_setup)

    check = sub.add_parser("check-deps", help="依存ツールの確認")
    check.set_defaults(func=cmd_check_deps)

    install = sub.add_parser("install-deps", help="承認済みの依存を取得")
    install.add_argument("--accept", required=True, help="cyanrip,ffmpeg,mutagen のうち承認されたもの")
    install.set_defaults(func=cmd_install_deps)

    drives = sub.add_parser("drives", help="光学ドライブの一覧")
    drives.set_defaults(func=cmd_drives)

    probe = sub.add_parser("probe", help="ディスク情報の取得")
    probe.add_argument("--drive")
    probe.set_defaults(func=cmd_probe)

    for name, func, help_text in (
        ("plan", cmd_plan, "確認用の出力計画を組み立てる"),
        ("run", cmd_run, "取り込み・エンコード・タグ付け・配置を実行"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--input", required=True, help="アルバム情報JSONのパス")
        command.add_argument("--drive")
        command.add_argument("--disc-track-count", type=int)
        command.add_argument("--no-probe", action="store_true", help="ディスク情報の取得を省く")
        if name == "run":
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--overwrite", action="store_true")
            command.add_argument("--work-dir")
            command.add_argument("--keep-work-dir", action="store_true")
        command.set_defaults(func=func)

    return parser


def _force_utf8_output() -> None:
    # Windows の既定コードページだと日本語のタグ名や全角記号が出力できず落ちる
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as exc:
        emit({"error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
