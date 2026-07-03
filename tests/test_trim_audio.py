"""Tests for io_adapters.encode.trim_audio (skipped when FFmpeg is missing)."""

import os
import re
import subprocess
import time

import pytest

from io_adapters.encode import ffmpeg_available, find_ffmpeg, trim_audio

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="FFmpeg not installed")


def _make_mp3(path, seconds):
    subprocess.run(
        [find_ffmpeg(), "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", "-b:a", "96k", str(path)],
        check=True, capture_output=True,
    )


def _duration(path):
    err = subprocess.run([find_ffmpeg(), "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def test_trim_cuts_to_requested_length(tmp_path):
    mp3 = tmp_path / "system.mp3"
    _make_mp3(mp3, 6)
    assert trim_audio(mp3, 2.0) is True
    # Stream copy cuts on frame boundaries: allow a small tolerance.
    assert _duration(mp3) < 2.6


def test_trim_keeps_original_timestamps(tmp_path):
    mp3 = tmp_path / "system.mp3"
    _make_mp3(mp3, 4)
    past = time.time() - 5 * 24 * 3600
    os.utime(mp3, (past, past))
    assert trim_audio(mp3, 1.0) is True
    assert abs(mp3.stat().st_mtime - past) < 2  # not the moment of trimming


def test_trim_rejects_nonpositive_end(tmp_path):
    mp3 = tmp_path / "system.mp3"
    _make_mp3(mp3, 2)
    before = mp3.read_bytes()
    assert trim_audio(mp3, 0) is False
    assert mp3.read_bytes() == before  # untouched


def test_trim_failure_leaves_original_and_no_tmp(tmp_path):
    bogus = tmp_path / "system.mp3"
    bogus.write_bytes(b"this is not audio")
    assert trim_audio(bogus, 5.0) is False
    assert bogus.read_bytes() == b"this is not audio"
    assert list(tmp_path.iterdir()) == [bogus]  # temp file cleaned up
