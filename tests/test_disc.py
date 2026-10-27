from pathlib import Path

import disc
import pytest

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


def test_collect_ripped_tracks_maps_by_number(tmp_path):
    rip = tmp_path / disc.RIP_SUBDIR
    rip.mkdir()
    for name in ("1.flac", "02.flac", "10 - Title.flac", "notes.txt"):
        (rip / name).write_bytes(b"")
    found = disc.collect_ripped_tracks(tmp_path, "flac")
    assert sorted(found) == [1, 2, 10]
    assert found[10].name == "10 - Title.flac"


def test_collect_ripped_tracks_falls_back_to_workdir(tmp_path):
    (tmp_path / "03.flac").write_bytes(b"")
    found = disc.collect_ripped_tracks(tmp_path, "flac")
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


TOC_FAILURE_OUTPUT = """\
Checking E: for cdrom...
Opening drive...
++ WARN: could not read TOC
Invalid number of tracks: 255!
"""


def test_toc_failure_is_detected():
    assert disc.toc_failed(TOC_FAILURE_OUTPUT) is True
    assert disc.toc_failed(SAMPLE_INDENTED) is False


def test_probe_discards_bogus_track_count_on_toc_failure(monkeypatch):
    class Completed:
        returncode = 1
        stdout = TOC_FAILURE_OUTPUT
        stderr = ""

    monkeypatch.setattr(disc, "build_probe_command", lambda cyanrip, drive: ["cyanrip"])
    monkeypatch.setattr(disc.subprocess, "run", lambda *a, **k: Completed())
    info = disc.probe_via_cyanrip("cyanrip", "E:")
    assert info["track_count"] == 0
    assert info["parse_confident"] is False
    assert "生アクセス" in info["error"]


def test_optional_flags_follow_binary_support(monkeypatch):
    monkeypatch.setattr(disc, "supported_flags", lambda cyanrip: frozenset("dINAUGKoDFB"))
    assert disc.optional_flags("cyanrip") == ["-B"]
    monkeypatch.setattr(disc, "supported_flags", lambda cyanrip: frozenset("dINAUGKoDF"))
    assert disc.optional_flags("cyanrip") == []


def test_supported_flags_parses_help_output(monkeypatch):
    help_text = """\
cyanrip 0.9.3 (063d848) help:

  Ripping options:
    -d <path>             Set device path
    -K                    Disable ReplayGain tagging

  Metadata options:
    -I                    Only print CD and track info
    -N                    Disables MusicBrainz lookup
"""

    class Completed:
        returncode = 0
        stdout = help_text
        stderr = ""

    monkeypatch.setattr(disc.subprocess, "run", lambda *a, **k: Completed())
    disc.supported_flags.cache_clear()
    flags = disc.supported_flags("cyanrip-help-test")
    assert flags == frozenset("dKIN")


def test_build_commands_include_base_flags(monkeypatch):
    monkeypatch.setattr(disc, "supported_flags", lambda cyanrip: frozenset("dINAUGKoDF"))
    probe_cmd = disc.build_probe_command("cyanrip", "E:")
    assert probe_cmd[:4] == ["cyanrip", "-d", "E:", "-I"]
    assert "-N" in probe_cmd and "-B" not in probe_cmd

    rip_cmd = disc.build_rip_command("cyanrip", "E:", "flac", 0)
    assert rip_cmd[rip_cmd.index("-o") + 1] == "flac"
    assert rip_cmd[rip_cmd.index("-F") + 1] == "{track}"
    assert rip_cmd[rip_cmd.index("-D") + 1] == disc.RIP_SUBDIR
    assert "-I" not in rip_cmd


def build_cda_stub(number: int, start_frame: int, length_frames: int) -> bytes:
    import struct

    data = bytearray(44)
    data[0:4] = b"RIFF"
    struct.pack_into("<I", data, 4, 36)
    data[8:12] = b"CDDA"
    data[12:16] = b"fmt "
    struct.pack_into("<I", data, 16, 24)
    struct.pack_into("<HH", data, 20, 1, number)
    struct.pack_into("<III", data, 24, 0x154800, start_frame, length_frames)
    return bytes(data)


def test_frames_to_duration():
    assert disc.frames_to_duration(15600) == "3:28.00"
    assert disc.frames_to_duration(0) == "0:00.00"
    assert disc.frames_to_duration(76) == "0:01.01"


def test_parse_cda_stub():
    parsed = disc.parse_cda_stub(build_cda_stub(2, 15600, 18000))
    assert parsed == {
        "number": 2,
        "duration": "4:00.00",
        "length_frames": 18000,
        "start_frame": 15600,
    }


def test_parse_cda_stub_rejects_non_cda():
    assert disc.parse_cda_stub(b"") is None
    assert disc.parse_cda_stub(b"RIFF" + b"\x00" * 40) is None
    assert disc.parse_cda_stub(build_cda_stub(0, 0, 100)) is None


def test_probe_prefers_cda_stubs(monkeypatch):
    stubs = [
        {"number": 1, "duration": "3:28.00", "length_frames": 15600, "start_frame": 0},
        {"number": 2, "duration": "4:00.00", "length_frames": 18000, "start_frame": 15600},
    ]
    monkeypatch.setattr(disc, "read_cda_stubs", lambda drive: stubs)
    info = disc.probe("E:")
    assert info["source"] == "cda"
    assert info["track_count"] == 2
    assert info["parse_confident"] is True


def test_probe_falls_back_to_cyanrip(monkeypatch):
    monkeypatch.setattr(disc, "read_cda_stubs", lambda drive: [])
    monkeypatch.setattr(
        disc, "probe_via_cyanrip", lambda cyanrip, drive: {"source": "cyanrip", "track_count": 9}
    )
    assert disc.probe("E:", "cyanrip")["track_count"] == 9


def test_probe_without_disc_or_cyanrip_raises(monkeypatch):
    monkeypatch.setattr(disc, "read_cda_stubs", lambda drive: [])
    with pytest.raises(RuntimeError, match="音楽CD"):
        disc.probe("E:")


def test_read_cda_stubs_reads_directory(tmp_path):
    (tmp_path / "Track02.cda").write_bytes(build_cda_stub(2, 15600, 18000))
    (tmp_path / "Track01.cda").write_bytes(build_cda_stub(1, 0, 15600))
    (tmp_path / "notes.txt").write_bytes(b"x")
    tracks = disc.read_cda_stubs(str(tmp_path))
    assert [track["number"] for track in tracks] == [1, 2]


def test_access_denied_hint_points_at_the_console_first():
    # コンソールなら非管理者でも通ることを実測しているため、まず session 種別を挙げる
    hint = disc.access_denied_hint({"elevated": False, "remote_session": True})
    assert "本体のコンソールから実行してください" in hint
    assert "コンソールなら管理者権限は不要" in hint
    # リモートのままの回避策としてのみ昇格に触れる
    assert "管理者として起動したセッションでなら通ります" in hint


def test_access_denied_hint_mentions_console_even_when_elevated():
    hint = disc.access_denied_hint({"elevated": True, "remote_session": True})
    assert "本体のコンソールから実行してください" in hint


def test_access_denied_hint_suggests_elevation_on_console():
    hint = disc.access_denied_hint({"elevated": False, "remote_session": False})
    assert "管理者として起動したセッションでやり直す" in hint
    assert "リモートデスクトップ" not in hint


def test_access_denied_hint_always_lists_disc_causes():
    hint = disc.access_denied_hint({"elevated": True, "remote_session": False})
    assert "音楽CDであること" in hint
    assert "占有していないこと" in hint
    assert "リモートデスクトップ" not in hint


def test_raw_access_context_returns_booleans():
    context = disc.raw_access_context()
    assert set(context) == {"elevated", "remote_session"}
    assert all(isinstance(value, bool) for value in context.values())


def test_raw_read_available_shape():
    result = disc.raw_read_available("E:")
    assert set(result) == {"available", "win32_error", "detail"}
    assert isinstance(result["available"], bool)


def test_raw_read_available_reports_missing_drive():
    result = disc.raw_read_available("Q:")
    assert result["available"] is False
    assert result["win32_error"] != 0


def test_access_denied_hint_always_notes_what_still_works():
    for elevated in (True, False):
        for remote in (True, False):
            hint = disc.access_denied_hint({"elevated": elevated, "remote_session": remote})
            assert "生アクセスなしでも動きます" in hint


FORMAT_HELP = """\
Supported output codecs:
	flac	folder: [FLAC]	extension: flac	(supports cover art)
	opus	folder: [OPUS]	extension: opus
	alac	folder: [ALAC]	extension: m4a
	mp3	folder: [MP3]	extension: mp3	(supports cover art)
"""


def _stub_run(monkeypatch, text):
    class Completed:
        returncode = 0
        stdout = text
        stderr = ""

    monkeypatch.setattr(disc.subprocess, "run", lambda *a, **k: Completed())
    disc.supported_formats.cache_clear()


def test_supported_formats_parses_help(monkeypatch):
    _stub_run(monkeypatch, FORMAT_HELP)
    formats = disc.supported_formats("cyanrip-fmt-test")
    assert formats == {"flac": "flac", "opus": "opus", "alac": "m4a", "mp3": "mp3"}


def test_pick_intermediate_format_prefers_flac(monkeypatch):
    _stub_run(monkeypatch, FORMAT_HELP)
    assert disc.pick_intermediate_format("cyanrip-fmt-test2") == ("flac", "flac")


def test_pick_intermediate_format_falls_back_to_next_lossless(monkeypatch):
    _stub_run(monkeypatch, FORMAT_HELP.replace("\tflac\tfolder: [FLAC]\textension: flac\t(supports cover art)\n", ""))
    assert disc.pick_intermediate_format("cyanrip-fmt-test3") == ("alac", "m4a")


def test_pick_intermediate_format_raises_without_lossless(monkeypatch):
    _stub_run(monkeypatch, "Supported output codecs:\n\tmp3\tfolder: [MP3]\textension: mp3\n")
    with pytest.raises(RuntimeError, match="可逆圧縮"):
        disc.pick_intermediate_format("cyanrip-fmt-test4")


def test_collect_ripped_tracks_honours_extension(tmp_path):
    rip = tmp_path / disc.RIP_SUBDIR
    rip.mkdir()
    (rip / "01.flac").write_bytes(b"")
    (rip / "02.wav").write_bytes(b"")
    assert sorted(disc.collect_ripped_tracks(tmp_path, "flac")) == [1]
    assert sorted(disc.collect_ripped_tracks(tmp_path, "wav")) == [2]


def test_build_rip_command_always_sets_offset(monkeypatch):
    monkeypatch.setattr(disc, "supported_flags", lambda cyanrip: frozenset("dINAUGKoDFs"))
    cmd = disc.build_rip_command("cyanrip", "E:", "flac")
    # 省略すると cyanrip が "Offset is unset!" で止まるため、常に渡す
    assert cmd[cmd.index("-s") + 1] == "0"
    cmd = disc.build_rip_command("cyanrip", "E:", "flac", 667)
    assert cmd[cmd.index("-s") + 1] == "667"


def test_build_probe_command_omits_offset(monkeypatch):
    monkeypatch.setattr(disc, "supported_flags", lambda cyanrip: frozenset("dINAUGKoDFs"))
    assert "-s" not in disc.build_probe_command("cyanrip", "E:")


def test_module_has_no_unused_access_denied_constant():
    assert not hasattr(disc, "ERROR_ACCESS_DENIED")
