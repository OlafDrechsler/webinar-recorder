from core.mic_segmenter import MicSegmenter


def test_starts_when_level_exceeds_threshold():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    assert seg.update(level=0.05, now=0) is None  # quiet, no segment
    assert not seg.is_active
    event = seg.update(level=0.5, now=1)
    assert event == ("start", 1)
    assert seg.is_active
    assert seg.current_start == 1


def test_quiet_alone_never_starts():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    for t in range(20):
        assert seg.update(level=0.0, now=t) is None
    assert not seg.is_active


def test_brief_silence_keeps_segment_open():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    seg.update(level=0.5, now=0)          # start
    # 5 s of silence — below the 10 s hangover, so stays open
    for t in range(1, 6):
        assert seg.update(level=0.0, now=t) is None
    assert seg.is_active


def test_long_silence_closes_segment_after_hangover():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    seg.update(level=0.5, now=0)          # start at 0, last loud = 0
    event = None
    for t in range(1, 12):
        event = seg.update(level=0.0, now=t)
        if event is not None:
            break
    assert event == ("stop", 0)           # closes once silence >= 10 s
    assert not seg.is_active


def test_loud_again_resets_silence_timer():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    seg.update(level=0.5, now=0)
    seg.update(level=0.0, now=5)          # 5 s silence
    seg.update(level=0.5, now=6)          # loud again -> timer resets
    # now another 9 s of silence should NOT close yet
    for t in range(7, 16):
        assert seg.update(level=0.0, now=t) is None
    assert seg.is_active


def test_manual_override_starts_even_when_quiet():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    event = seg.update(level=0.0, now=3, override=True)
    assert event == ("start", 3)
    assert seg.is_active
    # stays open while override held, despite silence beyond hangover
    for t in range(4, 30):
        assert seg.update(level=0.0, now=t, override=True) is None
    assert seg.is_active


def test_releasing_override_then_silence_closes_after_hangover():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    seg.update(level=0.0, now=0, override=True)   # start via override
    seg.update(level=0.0, now=5, override=True)   # still held
    # release override at t=5; silence countdown restarts from here
    event = None
    for t in range(6, 18):
        event = seg.update(level=0.0, now=t, override=False)
        if event is not None:
            break
    assert event == ("stop", 0)
    assert not seg.is_active


def test_finalize_reports_open_segment():
    seg = MicSegmenter(threshold=0.1, hangover_seconds=10)
    seg.update(level=0.5, now=2)
    assert seg.finalize() == ("stop", 2)   # closing an open segment
    assert not seg.is_active
    assert seg.finalize() is None          # nothing open now
