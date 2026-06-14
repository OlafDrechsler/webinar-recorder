from core.mic_playback import parse_segment_start, segment_local_offset


def test_parse_segment_start():
    assert parse_segment_start("mikro_00137.wav") == 137
    assert parse_segment_start("mikro_00000.mp3") == 0


def test_parse_segment_start_ignores_others():
    assert parse_segment_start("system.mp3") is None
    assert parse_segment_start("00137.png") is None


def test_segment_inactive_before_start():
    # segment starts at 10 s (10000 ms), duration 5 s
    assert segment_local_offset(start_ms=10000, duration_ms=5000, position_ms=9000) is None


def test_segment_active_within_window():
    assert segment_local_offset(start_ms=10000, duration_ms=5000, position_ms=12000) == 2000


def test_segment_inactive_after_end():
    assert segment_local_offset(start_ms=10000, duration_ms=5000, position_ms=16000) is None


def test_segment_active_at_exact_start():
    assert segment_local_offset(start_ms=10000, duration_ms=5000, position_ms=10000) == 0


def test_unknown_duration_treated_as_active_from_start():
    # Before Qt reports a duration (0), assume active once we pass the start.
    assert segment_local_offset(start_ms=10000, duration_ms=0, position_ms=12000) == 2000
    assert segment_local_offset(start_ms=10000, duration_ms=0, position_ms=9000) is None
