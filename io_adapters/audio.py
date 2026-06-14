"""Audio capture for Windows.

Two independent recorders:

* ``SystemAudioRecorder`` — the lecturer's sound via WASAPI loopback, written to
  one continuous WAV. This is the master timeline. WASAPI loopback only delivers
  data while something is playing, so a silent "keepalive" output stream is run
  alongside it to keep the audio engine active. That way the loopback delivers
  continuous samples from t0 (including silence), and the WAV stays in sync with
  the mic segments and slides instead of starting at the first sound.
* ``SegmentedMicRecorder`` — the microphone, split into short WAV segments that
  only exist while there is something to hear (driven by ``MicSegmenter``). Each
  segment file is named with its start-second so playback can re-align it
  (``mikro_00137.wav``). This avoids the giant silent track the old design
  produced and makes the timing unambiguous. The capture device is chosen via
  ``find_microphone_device`` (a real mic, not Stereomix/loopback) and can be
  switched live from the level-test window. It can also run in monitor mode
  (``start_monitor``) — the stream is open for level metering but writes no
  segments until ``enable_recording`` is called, so the threshold can be
  calibrated before recording starts.

Both stream to WAV on disk during recording; ``encode.py`` can transcode to MP3
on stop if FFmpeg is available.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from core.device_select import choose_input_device
from core.mic_segmenter import MicSegmenter

_INT16_MAX = 32768.0


def _pyaudio():
    import pyaudiowpatch as pyaudio

    return pyaudio


def find_loopback_device(pa) -> dict:
    """Return the WASAPI loopback device matching the default output."""
    pyaudio = _pyaudio()
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for dev in pa.get_loopback_device_info_generator():
        if default_out["name"] in dev["name"]:
            return dev
    for dev in pa.get_loopback_device_info_generator():
        return dev
    raise RuntimeError("No WASAPI loopback device found.")


def enumerate_input_devices(pa) -> list[dict]:
    """All capture-capable devices, each annotated with its host-API name."""
    devices = []
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            info = dict(info)
            info["hostApiName"] = pa.get_host_api_info_by_index(info["hostApi"])["name"]
            devices.append(info)
    return devices


def find_microphone_device(pa, preferred_name: str | None = None) -> dict:
    """Pick a real microphone (not Stereomix/loopback), honouring a saved choice.

    Falls back to the OS default input device if nothing better is found.
    """
    devices = enumerate_input_devices(pa)
    try:
        default_index = pa.get_default_input_device_info()["index"]
    except OSError:
        default_index = None
    chosen = choose_input_device(devices, default_index, preferred_name)
    if chosen is not None:
        return chosen
    return pa.get_default_input_device_info()


def rms_level(samples: np.ndarray) -> float:
    """Normalised RMS (0..~1) of int16 samples."""
    if samples.size == 0:
        return 0.0
    x = samples.astype(np.float64) / _INT16_MAX
    return float(np.sqrt(np.mean(x * x)))


class SystemAudioRecorder:
    def __init__(self, system_wav: Path) -> None:
        self._path = Path(system_wav)
        self._pa = None
        self._stream = None
        self._keepalive = None
        self._file = None

    def start(self) -> None:
        import soundfile as sf

        pyaudio = _pyaudio()
        self._pa = pyaudio.PyAudio()

        # Keepalive first: start rendering silence to the default output so the
        # audio engine is already running when the loopback capture begins. Then
        # the very first captured sample lines up with t0.
        self._start_keepalive(pyaudio)

        loop = find_loopback_device(self._pa)
        rate = int(loop["defaultSampleRate"])
        ch = int(loop["maxInputChannels"])
        self._file = sf.SoundFile(
            str(self._path), mode="w", samplerate=rate, channels=ch, subtype="PCM_16"
        )

        def cb(in_data, frame_count, time_info, status):
            samples = np.frombuffer(in_data, dtype=np.int16).reshape(-1, ch)
            self._file.write(samples)
            return (None, pyaudio.paContinue)

        self._stream = self._pa.open(
            format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
            input_device_index=loop["index"], frames_per_buffer=1024,
            stream_callback=cb,
        )
        self._stream.start_stream()

    def _start_keepalive(self, pyaudio) -> None:
        """Render continuous digital silence to the default output device.

        This keeps the WASAPI audio engine active so the loopback delivers data
        even when nothing else is playing. The silence is inaudible and is also
        what gets captured during quiet stretches, giving a gap-free timeline.
        Best-effort: if the output stream can't be opened, we simply fall back to
        the old behaviour (loopback may then start at the first real sound).
        """
        try:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            out = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            out_ch = min(int(out["maxOutputChannels"]), 2) or 2
            out_rate = int(out["defaultSampleRate"])

            def silence_cb(in_data, frame_count, time_info, status):
                # Return exactly the requested number of silent frames.
                return (b"\x00" * (frame_count * out_ch * 2), pyaudio.paContinue)

            self._keepalive = self._pa.open(
                format=pyaudio.paInt16, channels=out_ch, rate=out_rate, output=True,
                output_device_index=int(out["index"]), frames_per_buffer=1024,
                stream_callback=silence_cb,
            )
            self._keepalive.start_stream()
        except Exception:
            self._keepalive = None

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
        if self._keepalive is not None:
            try:
                self._keepalive.stop_stream()
                self._keepalive.close()
            except Exception:
                pass
            self._keepalive = None
        if self._pa is not None:
            self._pa.terminate()
        if self._file is not None:
            self._file.close()


class SegmentedMicRecorder:
    def __init__(
        self,
        out_dir: Path,
        start_time: float,
        threshold: float = 0.02,
        hangover_seconds: float = 10.0,
        device_name: str | None = None,
    ) -> None:
        self._dir = Path(out_dir)
        self._t0 = start_time
        self._segmenter = MicSegmenter(threshold, hangover_seconds)
        self._override = False
        # When False the stream runs for level metering only (monitor mode) and
        # writes no segment files. Flipped on by enable_recording()/start().
        self._record_enabled = True
        self._level = 0.0
        self._channels = 1
        self._rate = 44100
        # device_name is the *preferred* mic (e.g. the user's saved pick). The
        # real device is resolved in _open_stream and written back here.
        self._device_name = device_name
        self._pa = None
        self._stream = None
        self._file = None
        self._segments: list[Path] = []
        self._lock = threading.Lock()

    # --- live controls (called from GUI thread) ---
    def set_override(self, on: bool) -> None:
        self._override = on

    def set_threshold(self, value: float) -> None:
        self._segmenter.threshold = value

    @property
    def threshold(self) -> float:
        return self._segmenter.threshold

    @property
    def level(self) -> float:
        return self._level

    @property
    def is_active(self) -> bool:
        return self._segmenter.is_active

    @property
    def segments(self) -> list[Path]:
        return list(self._segments)

    @property
    def device_name(self) -> str | None:
        return self._device_name

    def available_devices(self) -> list[str]:
        """Unique input-device names for the picker (real mics first)."""
        from core.device_select import list_microphone_names

        if self._pa is None:
            return []
        return list_microphone_names(enumerate_input_devices(self._pa))

    def set_device(self, name: str) -> None:
        """Switch the active microphone (called from the level-test window).

        Stops the current stream, finishes any open segment, and reopens on the
        chosen device. Safe to call while recording (used during calibration).
        """
        with self._lock:
            self._stop_stream()
            self._device_name = name
            self._open_stream()

    # --- lifecycle ---
    def _callback(self, in_data, frame_count, time_info, status):
        pyaudio = _pyaudio()
        samples = np.frombuffer(in_data, dtype=np.int16).reshape(-1, self._channels)
        self._level = rms_level(samples)
        # Monitor mode: measure the level but don't segment or write anything.
        if not self._record_enabled:
            return (None, pyaudio.paContinue)
        now = time.monotonic() - self._t0
        event = self._segmenter.update(self._level, now, self._override)
        if event and event[0] == "start":
            self._open_segment(event[1])
        if self._file is not None:
            self._file.write(samples)
        if event and event[0] == "stop":
            self._close_segment()
        return (None, pyaudio.paContinue)

    def _open_stream(self) -> None:
        pyaudio = _pyaudio()
        mic = find_microphone_device(self._pa, self._device_name)
        self._device_name = mic["name"]  # remember what we actually opened
        self._rate = int(mic["defaultSampleRate"])
        self._channels = min(int(mic["maxInputChannels"]), 2) or 1
        self._stream = self._pa.open(
            format=pyaudio.paInt16, channels=self._channels, rate=self._rate,
            input=True, input_device_index=int(mic["index"]), frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        # Finish any segment that was open and reset the segmenter for a clean
        # restart on the new device.
        self._segmenter.finalize()
        self._close_segment()

    def start(self) -> None:
        """Open the stream and record segments immediately (full recording)."""
        self._record_enabled = True
        self._pa = _pyaudio().PyAudio()
        self._open_stream()

    def start_monitor(self) -> None:
        """Open the stream for level metering only — no segments are written.

        Lets the user calibrate the threshold (Mikro-Pegel-Test) before the
        recording is started. Call enable_recording() later to begin writing.
        """
        self._record_enabled = False
        self._pa = _pyaudio().PyAudio()
        self._open_stream()

    def enable_recording(self, t0: float) -> None:
        """Begin writing segments, using ``t0`` as the seconds-since-start origin.

        If a monitor stream is already running it is simply switched on (no audio
        gap); otherwise the stream is opened now.
        """
        self._t0 = t0
        if self._stream is None:
            self.start()
        else:
            self._record_enabled = True

    def _open_segment(self, start_sec: int) -> None:
        import soundfile as sf

        path = self._dir / f"mikro_{start_sec:05d}.wav"
        self._file = sf.SoundFile(
            str(path), mode="w", samplerate=self._rate,
            channels=self._channels, subtype="PCM_16",
        )
        self._segments.append(path)

    def _close_segment(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def stop(self) -> None:
        self._stop_stream()
        if self._pa is not None:
            self._pa.terminate()
