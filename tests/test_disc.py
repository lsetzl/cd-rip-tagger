from pathlib import Path

import disc

# cyanrip -I の実出力に合わせた固定書式ではなく、ラベル付きの書式ゆらぎに耐えるかを見る
SAMPLE_INDENTED = """\
cyanrip 0.9.0
Device:           E: (HL-DT-ST DVDRAM)
Number of tracks: 3
Total time:       12:17.33
Track 1:
    Preemphasis:      none detected
    Duration:         4:12.00
Track 2:
    Duration:         3:05.33
Track 3:
    Duration:         5:00.00
"""

SAMPLE_INLINE = """\
Track 1: 4:12.00
Track 2: 3:05.33
"""


def test_parse_indented_output():
    info = disc.parse_disc_info(SAMPLE_INDENTED)
    assert info["track_count"] == 3
    assert info["declared_track_count"] == 3
    assert info["parse_confident"] is True
    assert [track["duration"] for track in info["tracks"]] == ["4:12.00", "3:05.33", "5:00.00"]


def test_total_time_does_not_leak_into_last_track():
    info = disc.parse_disc_info(SAMPLE_INDENTED)
    assert info["tracks"][-1]["duration"] == "5:00.00"


def test_parse_inline_output_without_declared_count():
    info = disc.parse_disc_info(SAMPLE_INLINE)
    assert info["track_count"] == 2
    assert info["declared_track_count"] is None
    assert info["parse_confident"] is True


def test_parse_marks_unconfident_when_counts_disagree():
    info = disc.parse_disc_info("Number of tracks: 5\nTrack 1: 1:00.00\n")
    assert info["track_count"] == 5
    assert info["parse_confident"] is False


def test_parse_empty_output():
    info = disc.parse_disc_info("")
    assert info["track_count"] == 0
    assert info["parse_confident"] is False


def test_collect_ripped_wavs_maps_by_number(tmp_path):
    rip = tmp_path / disc.RIP_SUBDIR
    rip.mkdir()
    for name in ("1.wav", "02.wav", "10 - Title.wav", "notes.txt"):
        (rip / name).write_bytes(b"")
    found = disc.collect_ripped_wavs(tmp_path)
    assert sorted(found) == [1, 2, 10]
    assert found[10].name == "10 - Title.wav"


def test_collect_ripped_wavs_falls_back_to_workdir(tmp_path):
    (tmp_path / "03.wav").write_bytes(b"")
    found = disc.collect_ripped_wavs(tmp_path)
    assert sorted(found) == [3]


def test_resolve_drive_normalises_explicit(monkeypatch):
    monkeypatch.setattr(disc, "list_drives", lambda: [])
    assert disc.resolve_drive("d")[0] == "D:"
    assert disc.resolve_drive("E:")[0] == "E:"


def test_resolve_drive_auto_selects_single(monkeypatch):
    monkeypatch.setattr(disc, "list_drives", lambda: [{"drive": "F:", "caption": "x"}])
    assert disc.resolve_drive(None)[0] == "F:"


def test_resolve_drive_is_ambiguous_with_multiple(monkeypatch):
    monkeypatch.setattr(
        disc,
        "list_drives",
        lambda: [{"drive": "E:", "caption": "a"}, {"drive": "F:", "caption": "b"}],
    )
    drive, drives = disc.resolve_drive(None)
    assert drive is None
    assert len(drives) == 2
