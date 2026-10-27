import shutil
import struct
import wave
import zlib
from pathlib import Path

import config_store
import encode
import pytest
import tagging

pytest.importorskip("mutagen")
FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg が無い環境ではスキップ")

TITLE = "Re:Start = 夜明け＜序＞"
ALBUM = "アルバム／名"
ARTIST = "サークル名"


def make_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def make_wav(path: Path, seconds: float = 0.2) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00" * 2 * int(44100 * seconds))
    return path


def test_detect_mime_from_signature():
    assert tagging.detect_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert tagging.detect_mime(make_png()) == "image/png"
    assert tagging.detect_mime(b"not an image", "image/jpeg") == "image/jpeg"
    assert tagging.detect_mime(b"not an image") is None


@needs_ffmpeg
@pytest.mark.parametrize("quality", sorted(config_store.QUALITY_PRESETS))
def test_encode_produces_mp3(tmp_path, quality):
    wav = make_wav(tmp_path / "in.wav")
    mp3 = tmp_path / "out.mp3"
    encode.encode(FFMPEG, wav, mp3, quality)
    assert mp3.stat().st_size > 0


@needs_ffmpeg
def test_tags_roundtrip_as_id3v23_utf16(tmp_path):
    from mutagen.id3 import ID3

    wav = make_wav(tmp_path / "in.wav")
    mp3 = tmp_path / "01 track.mp3"
    encode.encode(FFMPEG, wav, mp3, "v2")
    tagging.write_tags(
        mp3,
        album=ALBUM,
        album_artist=ARTIST,
        title=TITLE,
        track=1,
        total_tracks=12,
        artist="歌い手",
        year="2025",
        cover={"mime": "image/png", "data": make_png()},
    )

    # translate=False にしないと mutagen が読み込み時に v2.4 相当へ変換してしまう
    tags = ID3(str(mp3), translate=False)
    assert tags.version[:2] == (2, 3)
    assert tags["TIT2"].text[0] == TITLE
    assert tags["TALB"].text[0] == ALBUM
    assert tags["TPE2"].text[0] == ARTIST
    assert tags["TPE1"].text[0] == "歌い手"
    assert tags["TRCK"].text[0] == "1/12"
    assert str(tags["TYER"].text[0]) == "2025"
    assert "TDRC" not in tags
    for frame in ("TIT2", "TALB", "TPE1", "TPE2"):
        assert tags[frame].encoding == 1, f"{frame} が UTF-16 ではない"
    apic = tags.getall("APIC")[0]
    assert apic.mime == "image/png"
    assert apic.type == 3
    assert apic.data == make_png()


@needs_ffmpeg
def test_no_id3v1_tag_is_written(tmp_path):
    wav = make_wav(tmp_path / "in.wav")
    mp3 = tmp_path / "out.mp3"
    encode.encode(FFMPEG, wav, mp3, "v2")
    tagging.write_tags(
        mp3, album=ALBUM, album_artist=ARTIST, title=TITLE, track=1, total_tracks=1
    )
    assert mp3.read_bytes()[-128:-125] != b"TAG"


@needs_ffmpeg
def test_track_artist_falls_back_to_album_artist(tmp_path):
    from mutagen.id3 import ID3

    wav = make_wav(tmp_path / "in.wav")
    mp3 = tmp_path / "out.mp3"
    encode.encode(FFMPEG, wav, mp3, "v2")
    tagging.write_tags(
        mp3, album=ALBUM, album_artist=ARTIST, title=TITLE, track=2, total_tracks=3
    )
    tags = ID3(str(mp3), translate=False)
    assert tags["TPE1"].text[0] == ARTIST
    assert "TYER" not in tags
