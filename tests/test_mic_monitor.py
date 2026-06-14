import numpy as np

from io_adapters.audio import SegmentedMicRecorder


def _loud_chunk(n=256):
    return (np.ones(n, dtype=np.int16) * 5000).tobytes()


def test_monitor_mode_measures_level_but_writes_nothing(tmp_path):
    rec = SegmentedMicRecorder(tmp_path, 0.0)
    rec._channels = 1
    rec._record_enabled = False  # as set by start_monitor()

    rec._callback(_loud_chunk(), 256, None, None)

    assert rec.level > 0          # level is metered for the Pegel-Test
    assert rec.segments == []     # but no segment file is created
    assert list(tmp_path.glob("*.wav")) == []


def test_enable_recording_sets_t0_and_flag_without_reopening(tmp_path):
    rec = SegmentedMicRecorder(tmp_path, 0.0)
    rec._stream = object()  # pretend a monitor stream is already running

    rec.enable_recording(12.0)

    assert rec._t0 == 12.0
    assert rec._record_enabled is True


def test_recording_callback_writes_a_segment_when_enabled(tmp_path):
    rec = SegmentedMicRecorder(tmp_path, 0.0, threshold=0.001)
    rec._channels = 1
    rec._record_enabled = True

    rec._callback(_loud_chunk(), 256, None, None)  # loud -> opens a segment
    assert rec.segments, "a segment should be opened while recording"
    rec._close_segment()
    assert list(tmp_path.glob("mikro_*.wav"))
