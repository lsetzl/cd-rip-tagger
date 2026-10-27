"""run サブコマンドの結線を、cyanrip をスタブ化して検証する（実CD不要）。"""
import json
import shutil
from pathlib import Path

import config_store
import deps
import disc
import pytest
import rip_and_tag
from test_tagging import make_png, make_wav

pytest.importorskip("mutagen")
FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg が無い環境ではスキップ")

ALBUM = {
    "album": "Re:Collection",
    "album_artist": "サークル名",
    "year": "2025",
    "tracks": [
        {"number": 1, "title": "一曲目 / 序", "artist": "歌い手"},
        {"number": 2, "title": "二曲目", "source_track": 3},
    ],
}


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    library = tmp_path / "library"
    config_store.save(str(library), "v2")

    input_path = tmp_path / "album.json"
    input_path.write_text(json.dumps(ALBUM, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        deps, "require_tools", lambda *names: {"cyanrip": "cyanrip", "ffmpeg": FFMPEG}
    )
    monkeypatch.setattr(disc, "resolve_drive", lambda explicit: ("E:", []))
    monkeypatch.setattr(
        disc,
        "probe",
        lambda cyanrip, drive: {"track_count": 3, "tracks": [], "parse_confident": True},
    )

    def fake_rip(cyanrip, drive, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        return {number: make_wav(workdir / f"{number:02d}.wav") for number in (1, 2, 3)}

    monkeypatch.setattr(disc, "rip_to_wav", fake_rip)
    return {"input": input_path, "library": library}


def run(args):
    return rip_and_tag.main(args)


def test_run_writes_tagged_files_to_library(staged, capsys):
    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 0
    result = json.loads(capsys.readouterr().out)

    out_dir = staged["library"] / "サークル名" / "Re：Collection"
    assert result["output_dir"] == str(out_dir)
    assert [Path(path).name for path in result["written"]] == [
        "01 一曲目 ／ 序.mp3",
        "02 二曲目.mp3",
    ]
    assert result["cover_embedded"] is False
    assert all(Path(path).stat().st_size > 0 for path in result["written"])

    from mutagen.id3 import ID3

    tags = ID3(result["written"][1], translate=False)
    assert tags["TIT2"].text[0] == "二曲目"
    assert tags["TRCK"].text[0] == "2/2"
    assert tags["TPE1"].text[0] == "サークル名"
    assert tags.version[:2] == (2, 3)


def test_run_maps_source_track(staged, monkeypatch):
    ripped = {}

    def recording_rip(cyanrip, drive, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        for number in (1, 2, 3):
            ripped[number] = make_wav(workdir / f"{number:02d}.wav", seconds=0.1 * number)
        return dict(ripped)

    monkeypatch.setattr(disc, "rip_to_wav", recording_rip)
    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 0

    out_dir = staged["library"] / "サークル名" / "Re：Collection"
    # 2曲目は source_track=3 なので、CDトラック2より長い3の尺になる
    assert (out_dir / "02 二曲目.mp3").stat().st_size > (out_dir / "01 一曲目 ／ 序.mp3").stat().st_size


def test_run_refuses_to_overwrite_without_flag(staged, capsys):
    out_dir = staged["library"] / "サークル名" / "Re：Collection"
    out_dir.mkdir(parents=True)
    (out_dir / "01 一曲目 ／ 序.mp3").write_bytes(b"old")

    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 1
    assert "--overwrite" in json.loads(capsys.readouterr().out)["error"]
    assert (out_dir / "01 一曲目 ／ 序.mp3").read_bytes() == b"old"

    assert run(["run", "--input", str(staged["input"]), "--drive", "E:", "--overwrite"]) == 0
    assert (out_dir / "01 一曲目 ／ 序.mp3").read_bytes() != b"old"


def test_run_fails_when_source_track_missing(staged, monkeypatch, capsys):
    def partial_rip(cyanrip, drive, workdir):
        workdir.mkdir(parents=True, exist_ok=True)
        return {1: make_wav(workdir / "01.wav")}

    monkeypatch.setattr(disc, "rip_to_wav", partial_rip)
    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 1
    assert "CDトラック 3 のWAVが見つかりません" in json.loads(capsys.readouterr().out)["error"]


def test_run_embeds_cover(staged, monkeypatch, capsys):
    raw = dict(ALBUM, cover_url="https://example.com/cover.png")
    staged["input"].write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    png = make_png()
    monkeypatch.setattr(
        rip_and_tag.tagging,
        "fetch_cover",
        lambda url: {"mime": "image/png", "data": png, "url": url},
    )
    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["cover_embedded"] is True

    from mutagen.id3 import ID3

    tags = ID3(result["written"][0], translate=False)
    assert tags.getall("APIC")[0].data == png


def test_run_dry_run_writes_nothing(staged, capsys):
    assert run(["run", "--input", str(staged["input"]), "--no-probe", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert not staged["library"].exists()


def test_run_cleans_up_work_dir(staged, monkeypatch):
    seen = {}

    def recording_rip(cyanrip, drive, workdir):
        seen["workdir"] = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        return {number: make_wav(workdir / f"{number:02d}.wav") for number in (1, 2, 3)}

    monkeypatch.setattr(disc, "rip_to_wav", recording_rip)
    assert run(["run", "--input", str(staged["input"]), "--drive", "E:"]) == 0
    assert not seen["workdir"].exists()
