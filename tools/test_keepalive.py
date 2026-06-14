"""Verify the silence-keepalive: record pure silence and confirm the loopback
still produced a continuous track of about the elapsed length."""

import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from io_adapters.audio import SystemAudioRecorder

out = Path("tools/_keepalive_test.wav")
rec = SystemAudioRecorder(str(out))
rec.start()
DURATION = 5.0
time.sleep(DURATION)  # play NOTHING during this time
rec.stop()

with wave.open(str(out), "rb") as w:
    frames = w.getnframes()
    rate = w.getframerate()
    secs = frames / rate if rate else 0
print(f"rate={rate}  frames={frames}  duration={secs:.2f}s  (recorded {DURATION}s of silence)")
print("RESULT:", "PASS (continuous timeline)" if secs >= DURATION * 0.8 else "FAIL (gap during silence)")
out.unlink(missing_ok=True)
