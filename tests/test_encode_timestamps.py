import os
import time

from io_adapters.encode import _copy_timestamps, _set_windows_creation_time


def test_copy_timestamps_carries_mtime(tmp_path):
    src = tmp_path / "a.wav"
    dst = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    dst.write_bytes(b"y")

    past = time.time() - 7 * 24 * 3600  # a week ago
    os.utime(src, (past, past))

    _copy_timestamps(src, dst)

    assert abs(dst.stat().st_mtime - past) < 2


def test_copy_timestamps_carries_windows_creation(tmp_path):
    if os.name != "nt":
        return  # creation-time copy is Windows-only

    src = tmp_path / "a.wav"
    dst = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    # dst created "now"
    dst.write_bytes(b"y")
    now = time.time()

    past = now - 30 * 24 * 3600  # a month ago
    os.utime(src, (past, past))
    _set_windows_creation_time(src, past)

    _copy_timestamps(src, dst)

    assert abs(dst.stat().st_ctime - past) < 2          # took the WAV's creation date
    assert abs(dst.stat().st_ctime - now) > 24 * 3600   # not the moment of conversion
