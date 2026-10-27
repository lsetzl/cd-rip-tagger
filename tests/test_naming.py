import naming


def test_invalid_characters_become_fullwidth():
    source = chr(92) + '/:*?"<>|'
    assert naming.sanitize_component(source) == "＼／：＊？＂＜＞｜"
    assert naming.sanitize_component("Re:Start / 夜明け") == "Re：Start ／ 夜明け"


def test_trailing_dots_and_spaces_removed():
    assert naming.sanitize_component("名前...  ") == "名前"
    assert naming.sanitize_component("  前後  ") == "前後"


def test_control_characters_and_newlines_collapse():
    assert naming.sanitize_component("a\nb\tc") == "a b c"


def test_empty_falls_back():
    assert naming.sanitize_component("") == "_"
    assert naming.sanitize_component("...", fallback="X") == "X"


def test_reserved_device_names_are_escaped():
    assert naming.sanitize_component("CON") == "_CON"
    assert naming.sanitize_component("nul.mp3") == "_nul.mp3"
    assert naming.sanitize_component("CONcert") == "CONcert"


def test_track_filename_is_zero_padded():
    assert naming.track_filename(1, "曲名") == "01 曲名.mp3"
    assert naming.track_filename(12, "Re:Start") == "12 Re：Start.mp3"
    assert naming.track_filename(3, "") == "03 Track 03.mp3"


def test_album_dir_uses_album_artist():
    path = naming.album_dir(r"D:\Music", "サークル/名", "アルバム:名")
    assert path.parts[-2:] == ("サークル／名", "アルバム：名")


def test_path_warnings_flags_long_paths():
    from pathlib import Path

    assert naming.path_warnings([Path("D:/short.mp3")]) == []
    long_path = Path("D:/" + "a" * 300 + ".mp3")
    assert len(naming.path_warnings([long_path])) == 1
