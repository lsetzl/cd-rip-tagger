import json

import album
import pytest


def sample():
    return {
        "album": "Album",
        "album_artist": "Circle",
        "year": "2025",
        "cover_url": "https://example.com/cover.jpg",
        "tracks": [
            {"number": 1, "title": "One", "artist": "Singer"},
            {"number": 2, "title": "Two"},
        ],
    }


def test_validate_fills_defaults():
    data = album.validate(sample())
    assert data["tracks"][1] == {
        "number": 2,
        "title": "Two",
        "artist": None,
        "source_track": 2,
    }


def test_validate_sorts_by_number_and_keeps_source_track():
    raw = sample()
    raw["tracks"] = [
        {"number": 2, "title": "Two", "source_track": 3},
        {"number": 1, "title": "One"},
    ]
    data = album.validate(raw)
    assert [track["number"] for track in data["tracks"]] == [1, 2]
    assert data["tracks"][1]["source_track"] == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.pop("album"),
        lambda raw: raw.pop("album_artist"),
        lambda raw: raw.update(tracks=[]),
        lambda raw: raw.update(tracks=[{"number": 1}]),
        lambda raw: raw.update(tracks=[{"number": "x", "title": "t"}]),
    ],
)
def test_validate_rejects_bad_input(mutate):
    raw = sample()
    mutate(raw)
    with pytest.raises(RuntimeError):
        album.validate(raw)


def test_load_reads_utf8(tmp_path):
    path = tmp_path / "album.json"
    raw = sample()
    raw["album"] = "アルバム"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert album.load(path)["album"] == "アルバム"


def test_build_plan_paths_and_warnings(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    plan = album.build_plan(album.validate(sample()), config)
    assert plan["output_dir"] == str(tmp_path / "Circle" / "Album")
    assert [file["filename"] for file in plan["files"]] == ["01 One.mp3", "02 Two.mp3"]
    assert plan["files"][1]["artist"] == "Circle"
    assert plan["files"][1]["artist_is_fallback"] is True
    assert any("アルバムアーティストで埋めます" in warning for warning in plan["warnings"])


def test_build_plan_warns_on_track_count_mismatch(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    plan = album.build_plan(album.validate(sample()), config, disc_track_count=5)
    assert any("一致しません" in warning for warning in plan["warnings"])


def test_build_plan_warns_on_missing_year_and_cover(tmp_path):
    raw = sample()
    raw.pop("year")
    raw.pop("cover_url")
    config = {"library_root": str(tmp_path), "quality": "v2"}
    plan = album.build_plan(album.validate(raw), config)
    assert any("年タグは空" in warning for warning in plan["warnings"])
    assert any("画像は埋め込まれません" in warning for warning in plan["warnings"])


def test_build_plan_detects_existing_files(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    out = tmp_path / "Circle" / "Album"
    out.mkdir(parents=True)
    (out / "01 One.mp3").write_bytes(b"")
    plan = album.build_plan(album.validate(sample()), config)
    assert plan["existing_files"] == [str(out / "01 One.mp3")]
    assert any("上書き" in warning for warning in plan["warnings"])


def test_validate_rejects_source_track_below_one():
    raw = sample()
    raw["tracks"] = [{"number": 1, "title": "T", "source_track": 0}]
    with pytest.raises(RuntimeError, match="source_track が1未満"):
        album.validate(raw)


def test_build_plan_rejects_source_track_beyond_disc(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    raw = sample()
    raw["tracks"] = [{"number": 1, "title": "T", "source_track": 9}]
    data = album.validate(raw)
    # リッピングで必ず失敗するので、確認画面に進む前に止める
    with pytest.raises(RuntimeError, match="source_track がCDのトラック数"):
        album.build_plan(data, config, disc_track_count=4)


def test_build_plan_allows_source_track_equal_to_disc_count(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    raw = sample()
    raw["tracks"] = [{"number": 1, "title": "T", "source_track": 4}]
    plan = album.build_plan(album.validate(raw), config, disc_track_count=4)
    assert plan["files"][0]["source_track"] == 4


def test_build_plan_skips_range_check_without_disc_count(tmp_path):
    config = {"library_root": str(tmp_path), "quality": "v2"}
    raw = sample()
    raw["tracks"] = [{"number": 1, "title": "T", "source_track": 99}]
    plan = album.build_plan(album.validate(raw), config)
    assert plan["files"][0]["source_track"] == 99
