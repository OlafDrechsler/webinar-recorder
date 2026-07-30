"""Optional post-recording transcode of WAV tracks to MP3 via FFmpeg.

MP3 (not Opus) is used so the bundled player — and any standard Windows media
app — can play the result without extra codecs. If FFmpeg cannot be found at all,
the WAV file is kept as-is and its path returned, so a recording is never lost
just because the encoder is missing.

Finding FFmpeg: we do NOT rely on the PATH alone. When the app is launched from
the desktop shortcut (pythonw) the process can inherit a stale PATH that doesn't
yet include a freshly winget-installed FFmpeg — that produced WAV instead of MP3.
``find_ffmpeg()`` therefore also probes the well-known install locations
(winget's Links shim and package folder, Chocolatey, common manual unzips).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# Cache the resolved path so we only hit the disk search once per run.
_cached: str | None = None
_searched = False

# Stop each FFmpeg call from flashing a console window when the app is launched
# via pythonw (no console). 0 on non-Windows, so it's harmless there.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _candidate_paths() -> list[Path]:
    """Well-known places FFmpeg ends up, in addition to the PATH."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        local_path = Path(local)
        # winget shim directory (this is what winget adds to the user PATH).
        candidates.append(local_path / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe")
        # winget package install folder; version is in the folder name -> glob.
        pkgs = local_path / "Microsoft" / "WinGet" / "Packages"
        candidates += sorted(pkgs.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))

    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(Path(program_data) / "chocolatey" / "bin" / "ffmpeg.exe")

    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates += sorted(Path(base).glob("ffmpeg*/**/bin/ffmpeg.exe"))

    # Common manual-unzip locations.
    candidates.append(Path("C:/ffmpeg/bin/ffmpeg.exe"))
    return candidates


def find_ffmpeg() -> str | None:
    """Absolute path to ffmpeg.exe (PATH first, then known locations), or None."""
    global _cached, _searched
    if _searched:
        return _cached

    found = shutil.which("ffmpeg")
    if not found:
        for cand in _candidate_paths():
            if cand.is_file():
                found = str(cand)
                break

    _cached = found
    _searched = True
    return _cached


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def _parse_db(text: str, key: str) -> float | None:
    """Pull a "<key>: -12.3 dB" value out of FFmpeg's volumedetect output."""
    match = re.search(rf"{key}:\s*(-?\d+(?:\.\d+)?) dB", text)
    return float(match.group(1)) if match else None


def measure_levels(path: Path) -> tuple[float | None, float | None]:
    """Measure (mean_dB, max_dB) of an audio file via FFmpeg's volumedetect.

    Returns (None, None) if FFmpeg is missing or the measurement fails, so the
    caller treats the track as "leave as-is".
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return (None, None)
    cmd = [
        ffmpeg, "-hide_banner", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    except OSError:
        return (None, None)
    # volumedetect prints its stats to stderr.
    text = proc.stderr or ""
    return (_parse_db(text, "mean_volume"), _parse_db(text, "max_volume"))


def _loudnorm_value(value) -> float | None:
    """Parse one loudnorm JSON number; treat the silence floor / -inf as None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f <= -70.0:  # NaN, -inf, or the measurement floor (silence)
        return None
    return f


def parse_loudnorm_json(text: str) -> tuple[float | None, float | None]:
    """Extract (integrated_LUFS, true_peak_dBTP) from loudnorm's JSON output."""
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return (None, None)
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return (None, None)
    return (_loudnorm_value(data.get("input_i")), _loudnorm_value(data.get("input_tp")))


def measure_loudness(path: Path) -> tuple[float | None, float | None]:
    """Measure (integrated loudness in LUFS, true peak in dBTP) via EBU R128.

    FFmpeg's ``loudnorm`` filter gates out silence, so long quiet stretches do not
    drag the measurement down (unlike a plain mean). Returns (None, None) if
    FFmpeg is missing, the file is unmeasurable, or it is effectively silent.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return (None, None)
    cmd = [
        ffmpeg, "-hide_banner", "-i", str(path),
        "-af", "loudnorm=I=-16:TP=-1.0:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    except OSError:
        return (None, None)
    return parse_loudnorm_json(proc.stderr or "")


def _set_windows_creation_time(path: Path, epoch_seconds: float) -> None:
    """Set a file's Windows creation timestamp (the stdlib only sets a/mtime)."""
    try:
        import ctypes
        from ctypes import wintypes

        # FILETIME = 100-ns ticks since 1601-01-01; epoch is 1970-01-01.
        ticks = int(epoch_seconds * 10_000_000) + 116444736000000000
        if ticks < 0:
            return
        filetime = wintypes.FILETIME(ticks & 0xFFFFFFFF, (ticks >> 32) & 0xFFFFFFFF)
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.restype = ctypes.c_void_p
        FILE_WRITE_ATTRIBUTES = 0x100
        OPEN_EXISTING = 3
        handle = kernel32.CreateFileW(str(path), FILE_WRITE_ATTRIBUTES, 0, None, OPEN_EXISTING, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return
        try:
            kernel32.SetFileTime(ctypes.c_void_p(handle), ctypes.byref(filetime), None, None)
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass  # never let a timestamp tweak break the transcode


def _copy_timestamps(src: Path, dst: Path) -> None:
    """Carry the source file's timestamps over to ``dst`` so the MP3 keeps the
    WAV's original date instead of the moment of conversion. On Windows the
    creation time is copied too (st_ctime), not just access/modified."""
    try:
        st = src.stat()
    except OSError:
        return
    try:
        os.utime(dst, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    if os.name == "nt":
        _set_windows_creation_time(dst, st.st_ctime)


def trim_audio(path: Path, end_seconds: float) -> bool:
    """Cut an audio file in place to ``[0, end_seconds]`` (lossless stream copy).

    Used to discard an over-long tail (e.g. when the user forgot to stop the
    recording). Returns True on success; on any failure the original is left
    untouched. The original timestamps are preserved on the trimmed file.

    Note: the caller must release any open handle on ``path`` first (on Windows a
    file that a media player still has open cannot be replaced).
    """
    path = Path(path)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None or end_seconds <= 0:
        return False
    tmp = path.with_name(f"{path.stem}_trim{path.suffix}")
    cmd = [ffmpeg, "-y", "-i", str(path), "-t", f"{end_seconds:.3f}", "-c", "copy", str(tmp)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, creationflags=_NO_WINDOW)
    except (subprocess.CalledProcessError, OSError):
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    _copy_timestamps(path, tmp)  # keep the recording's date, not now
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def trim_audio_start(path: Path, start_seconds: float) -> bool:
    """Cut an audio file in place to ``[start_seconds, end]`` (lossless stream copy),
    so the kept part now starts at 0.

    Mirror of :func:`trim_audio` for discarding the BEGINNING of a recording.
    Returns True on success; on any failure the original is left untouched. The
    original timestamps are preserved. The caller must release any open handle on
    ``path`` first (Windows locks files a media player still has open)."""
    path = Path(path)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None or start_seconds <= 0:
        return False
    tmp = path.with_name(f"{path.stem}_trim{path.suffix}")
    # -ss before -i seeks fast; -avoid_negative_ts make_zero re-bases timestamps to 0.
    cmd = [ffmpeg, "-y", "-ss", f"{start_seconds:.3f}", "-i", str(path),
           "-c", "copy", "-avoid_negative_ts", "make_zero", str(tmp)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, creationflags=_NO_WINDOW)
    except (subprocess.CalledProcessError, OSError):
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    _copy_timestamps(path, tmp)  # keep the recording's date, not now
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


_DURATION = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def audio_duration(path: Path) -> float | None:
    """Length of an audio file in seconds, or None if it can't be determined.

    Parsed from ``ffmpeg -i`` (which prints "Duration: HH:MM:SS.ss" to stderr and
    exits non-zero because no output is given — that's expected). Used to tell
    whether a mic segment spans a cut point."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return None
    try:
        proc = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True,
                              creationflags=_NO_WINDOW)
    except OSError:
        return None
    text = proc.stderr.decode("utf-8", "replace")
    m = _DURATION.search(text)
    if not m:
        return None
    h, mnt, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + sec


def transcode_to_mp3(
    wav_path: Path, bitrate: str = "96k", delete_wav: bool = True, gain_db: float = 0.0
) -> Path:
    """Transcode ``wav_path`` to a sibling .mp3 file. Returns the kept file.

    ``gain_db`` (if non-zero) applies a volume adjustment during the transcode,
    used to loudness-match the system and mic tracks. Falls back to the original
    WAV (returned unchanged) if FFmpeg cannot be found or the transcode fails.

    The MP3 inherits the WAV's timestamps (incl. the Windows creation date) so it
    keeps the recording's date rather than the conversion time.
    """
    wav_path = Path(wav_path)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return wav_path

    mp3_path = wav_path.with_suffix(".mp3")
    cmd = [ffmpeg, "-y", "-i", str(wav_path)]
    if abs(gain_db) >= 0.1:  # skip negligible adjustments
        cmd += ["-af", f"volume={gain_db:.2f}dB"]
    cmd += ["-c:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, creationflags=_NO_WINDOW)
    except (subprocess.CalledProcessError, OSError):
        return wav_path

    _copy_timestamps(wav_path, mp3_path)  # while the WAV still exists

    if delete_wav:
        try:
            wav_path.unlink()
        except OSError:
            pass
    return mp3_path
