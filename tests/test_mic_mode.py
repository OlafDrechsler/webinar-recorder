import numpy as np

from io_adapters.audio import SegmentedMicRecorder


def _chunk(value, n=256):
    return (np.ones(n, dtype=np.int16) * value).tobytes()


def _rec(tmp_path, threshold):
    rec = SegmentedMicRecorder(tmp_path, 0.0, threshold=threshold)
    rec._channels = 1
    rec._record_enabled = True  # as after enable_recording()
    return rec


def test_off_writes_nothing_even_when_loud(tmp_path):
    rec = _rec(tmp_path, threshold=0.001)
    rec.set_mic_mode("off")
    rec._callback(_chunk(5000), 256, None, None)
    assert rec.segments == []
    assert list(tmp_path.glob("*.wav")) == []


def test_on_records_even_when_quiet(tmp_path):
    rec = _rec(tmp_path, threshold=1.0)  # so auto would never trigger
    rec.set_mic_mode("on")
    rec._callback(_chunk(100), 256, None, None)  # very quiet
    assert rec.segments
    rec._close_segment()


def test_auto_stays_silent_below_threshold(tmp_path):
    rec = _rec(tmp_path, threshold=1.0)  # default mode "auto"
    rec._callback(_chunk(100), 256, None, None)
    assert rec.segments == []


def test_switch_to_off_closes_open_segment(tmp_path):
    rec = _rec(tmp_path, threshold=0.001)
    rec.set_mic_mode("on")
    rec._callback(_chunk(5000), 256, None, None)
    assert rec._file is not None
    rec.set_mic_mode("off")
    rec._callback(_chunk(5000), 256, None, None)
    assert rec._file is None


def test_set_override_maps_to_modes(tmp_path):
    rec = SegmentedMicRecorder(tmp_path, 0.0)
    rec.set_override(True)
    assert rec.mode == "on"
    rec.set_override(False)
    assert rec.mode == "auto"
