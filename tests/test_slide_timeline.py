from core.slide_timeline import build_timeline, slide_for_second, parse_seconds


def test_parse_seconds_auto_frame():
    assert parse_seconds("00137.png") == 137
    assert parse_seconds("00000.png") == 0


def test_parse_seconds_ignores_marked_and_others():
    # Marked frames are annotated extras, not part of the auto slideshow.
    assert parse_seconds("00137_markiert_01.png") is None
    assert parse_seconds("notes.txt") is None


def test_build_timeline_sorted_auto_frames_only():
    files = ["00050.png", "00010.png", "00010_markiert_01.png", "x.txt"]
    assert build_timeline(files) == [(10, "00010.png"), (50, "00050.png")]


def test_slide_for_second_picks_latest_not_after_t():
    timeline = [(10, "00010.png"), (50, "00050.png")]
    assert slide_for_second(timeline, 5) is None      # before first slide
    assert slide_for_second(timeline, 10) == "00010.png"
    assert slide_for_second(timeline, 49) == "00010.png"
    assert slide_for_second(timeline, 50) == "00050.png"
    assert slide_for_second(timeline, 9999) == "00050.png"


def test_slide_for_second_empty_timeline():
    assert slide_for_second([], 100) is None
