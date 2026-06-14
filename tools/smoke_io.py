"""Manual smoke tests for the hardware-bound adapters.

Run from the project root:
    python tools/smoke_io.py screen      # grab one frame, report shape
    python tools/smoke_io.py devices     # list audio devices + loopback
    python tools/smoke_io.py audio 5     # record 5 s of system+mic to ./_smoke
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def smoke_screen() -> None:
    from io_adapters.screen import Region, ScreenCapturer

    with ScreenCapturer() as cap:
        frame = cap.grab(Region(0, 0, 400, 300))
    print("Grabbed frame:", frame.shape, frame.dtype)
    assert frame.shape == (300, 400, 3)
    print("OK: screen capture works.")


def smoke_devices() -> None:
    import pyaudiowpatch as pyaudio
    from io_adapters.audio import find_loopback_device

    pa = pyaudio.PyAudio()
    try:
        mic = pa.get_default_input_device_info()
        print("Default mic:", mic["name"], int(mic["defaultSampleRate"]), "Hz")
        loop = find_loopback_device(pa)
        print("Loopback   :", loop["name"], int(loop["defaultSampleRate"]), "Hz")
        print("OK: audio devices found.")
    finally:
        pa.terminate()


def smoke_audio(seconds: int) -> None:
    from io_adapters.audio import SegmentedMicRecorder, SystemAudioRecorder

    out = Path("_smoke")
    (out / "mikro").mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    system = SystemAudioRecorder(out / "system.wav")
    mic = SegmentedMicRecorder(out / "mikro", t0, threshold=0.02)
    print(f"Recording {seconds}s... play sound (system) and speak (mic) now.")
    system.start()
    mic.start()
    time.sleep(seconds)
    system.stop()
    mic.stop()
    print("System bytes:", (out / "system.wav").stat().st_size)
    print("Mic segments:", [p.name for p in mic.segments])
    print("OK: audio capture works.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "screen"
    if cmd == "screen":
        smoke_screen()
    elif cmd == "devices":
        smoke_devices()
    elif cmd == "audio":
        smoke_audio(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    else:
        print("Unknown command:", cmd)
