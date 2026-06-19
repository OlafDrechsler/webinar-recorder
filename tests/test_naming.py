from core.naming import auto_frame_name, marked_frame_name


def test_auto_frame_name_zero_padded():
    assert auto_frame_name(0) == "00000.png"
    assert auto_frame_name(137) == "00137.png"


def test_auto_frame_name_handles_long_webinars():
    # > 99999 s (27.7 h) should still produce a sortable name, not crash.
    assert auto_frame_name(100000) == "100000.png"


def test_marked_frame_name_starts_at_01():
    assert marked_frame_name(137, existing=[]) == "00137_edit_01.png"


def test_marked_frame_name_increments_past_existing():
    existing = ["00137.png", "00137_edit_01.png", "00137_edit_02.png"]
    assert marked_frame_name(137, existing=existing) == "00137_edit_03.png"


def test_marked_frame_name_counts_legacy_markiert():
    # Old "_markiert_" files still count so we never collide on disk.
    existing = ["00137_markiert_01.png", "00137_markiert_02.png"]
    assert marked_frame_name(137, existing=existing) == "00137_edit_03.png"


def test_marked_frame_name_counts_only_same_second():
    existing = ["00137_edit_01.png", "00200_edit_01.png"]
    assert marked_frame_name(200, existing=existing) == "00200_edit_02.png"


def test_marked_frame_name_ignores_unrelated_files():
    existing = ["notes.txt", "00137.png", "thumb_00137_edit_01.png"]
    assert marked_frame_name(137, existing=existing) == "00137_edit_01.png"
