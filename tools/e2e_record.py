"""End-to-end recording smoke test.

Starts the system + segmented-mic recorders, plays a couple of beeps, forces a
mic segment via override, stops, then transcodes everything to MP3. Prints a
PASS/FAIL summary. Run from the project root with FFmpeg on PATH.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from io_adapters.audio import SystemAudioRecorder, SegmentedMicRecorder
from io_adapters.encode import ffmpeg_available, transcode_to_mp3


def _beep(freq: float = 440.0, secs: float = 0.6) -> None:
    try:
        import winsound

        winsound.Beep(int(freq), int(secs * 1000))
    except Exception:
        time.sleep(secs)


def main() -> int:
    out = Path("tools/_e2e_out")
    out.mkdir(parents=True, exist_ok=True)
    mic_dir = out / "mikro"
    mic_dir.mkdir(exist_ok=True)
    system_wav = out / "system.wav"

    print("ffmpeg available:", ffmpeg_available())

    t0 = time.monotonic()
    system = SystemAudioRecorder(str(system_wav))
    mic = SegmentedMicRecorder(str(mic_dir), start_time=t0)

    system.start()
    mic.start()

    # Play audio so WASAPI loopback delivers data.
    _beep(440, 0.6)
    _beep(660, 0.6)

    # Force a mic segment.
    mic.set_override(True)
    time.sleep(1.5)
    mic.set_override(False)
    time.sleep(0.3)

    _beep(880, 0.5)

    mic.stop()
    system.stop()

    # --- check system.wav ---
    sys_ok = False
    if system_wav.exists():
        with wave.open(str(system_wav), "rb") as w:
            frames = w.getnframes()
        size = system_wav.stat().st_size
        sys_ok = frames > 0 and size > 1000
        print(f"system.wav: {size} bytes, {frames} frames -> {'OK' if sys_ok else 'EMPTY'}")
    else:
        print("system.wav: MISSING")

    # --- check mic segments ---
    segs = sorted(mic_dir.glob("mikro_*.wav"))
    print(f"mic segments: {[p.name for p in segs]}")
    seg_ok = len(segs) >= 1

    # --- transcode ---
    mp3_ok = False
    if ffmpeg_available():
        sys_mp3 = transcode_to_mp3(system_wav)
        seg_mp3s = [transcode_to_mp3(p) for p in segs]
        print("system mp3:", sys_mp3)
        print("segment mp3s:", seg_mp3s)
        mp3_ok = sys_mp3 is not None and str(sys_mp3).endswith(".mp3")
    else:
        print("ffmpeg not on PATH -> skipping transcode (WAV fallback)")
        mp3_ok = True  # acceptable fallback

    ok = sys_ok and seg_ok and mp3_ok
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
