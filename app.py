"""Webinar recorder — entry point.

Continuous system audio + voice-activated microphone segments, plus a 1 Hz
screenshot of a chosen region that is saved only when the slide changes.

Flow:
1. The control window opens immediately with the storage folder shown in its
   header (pre-filled from settings; changeable there — like the player).
2. The user positions the window and picks the slide region.
3. The user clicks "Aufnahme starten" — only now is the session folder created
   and audio + screenshots begin. Clicking again ("Aufnahme beenden") stops and
   then loudness-matches + transcodes to MP3.

Run:  python app.py     (or use the WebinarOD launcher created by install.ps1)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from core.i18n import tr
from core.loudness import aggregate_mean_db, compute_gain_db
from core.settings import get_mic_device
from gui.branding import app_icon
from gui.control_window import ControlWindow
from io_adapters.encode import ffmpeg_available, measure_loudness, transcode_to_mp3


def launch_recording() -> ControlWindow:
    """Create and show the recording control window (storage folder is chosen in
    its header). The loudness-match + MP3 transcode runs when the window closes.
    Usable from the hub (no QApplication ownership)."""

    def on_process(system_wav: Path, segments: list[Path]) -> None:
        if ffmpeg_available():
            _run_postprocessing_with_progress(system_wav, segments)
        print(f"Aufnahme gespeichert: {system_wav.parent} | Mikro-Segmente: {len(segments)}")

    window = ControlWindow(get_mic_device(), on_process)
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.show()
    return window


def main() -> int:
    from core.i18n import init_language

    # Use the exact (possibly fractional) display scale so devicePixelRatioF
    # reports e.g. 1.5 on a 150% display (needed for the region selector). Must be
    # set before the QApplication is created.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    init_language()

    window = launch_recording()
    window.destroyed.connect(app.quit)
    return app.exec()


def _normalize_and_transcode(system_wav: Path, mic_segments: list[Path], progress=None) -> None:
    """Loudness-match system + mic, then transcode all tracks to MP3.

    Loudness is EBU R128 integrated loudness (LUFS), which ignores silence, with
    a true-peak cap so no clipping is introduced. The system track gets its own
    gain. All mic segments share ONE gain (from their combined loudness) so their
    relative dynamics stay intact while their overall loudness matches the system
    track. Measuring happens before transcode because transcode deletes the WAV.

    ``progress(label, done, total)`` is called before each step for the UI.
    """
    total = 1 + len(mic_segments)

    def step(label: str, done: int) -> None:
        if progress is not None:
            progress(label, done, total)

    step(tr("progress.system"), 0)
    sys_lufs, sys_tp = measure_loudness(system_wav)
    transcode_to_mp3(system_wav, gain_db=compute_gain_db(sys_lufs, sys_tp))

    n = len(mic_segments)
    if n:
        measured = []
        for i, seg in enumerate(mic_segments):
            step(tr("progress.analyze_seg", i=i + 1, n=n), 1)
            measured.append(measure_loudness(seg))
        mic_lufs = aggregate_mean_db([lufs for lufs, _ in measured])
        peaks = [tp for _, tp in measured if tp is not None]
        mic_gain = compute_gain_db(mic_lufs, max(peaks) if peaks else None)
        for i, seg in enumerate(mic_segments):
            step(tr("progress.convert_seg", i=i + 1, n=n), 1 + i)
            transcode_to_mp3(seg, gain_db=mic_gain)
    step(tr("progress.done"), total)


class _TranscodeWorker(QObject):
    """Runs the (blocking) FFmpeg work off the GUI thread so the progress window
    stays responsive (no "Not responding")."""

    progress = Signal(str)
    finished = Signal()

    def __init__(self, system_wav: Path, segments: list[Path]) -> None:
        super().__init__()
        self._system_wav = system_wav
        self._segments = segments

    def run(self) -> None:
        def report(label: str, done: int, total: int) -> None:
            self.progress.emit(f"{tr('progress.processing')}\n{label} ({done}/{total})")

        _normalize_and_transcode(self._system_wav, self._segments, progress=report)
        self.finished.emit()


def _run_postprocessing_with_progress(system_wav: Path, segments: list[Path]) -> None:
    # Indeterminate (marquee) progress so it visibly keeps moving during the long
    # system-track transcode; the actual work runs in a worker thread.
    dialog = QProgressDialog(tr("progress.processing"), None, 0, 0)
    dialog.setWindowTitle(tr("progress.wait_title"))
    # Non-modal so the hub stays usable during the transcode (e.g. start sorting
    # slides while the audio is still being processed).
    dialog.setWindowModality(Qt.NonModal)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(0)
    dialog.show()

    thread = QThread()
    worker = _TranscodeWorker(system_wav, segments)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(dialog.setLabelText)  # queued onto the GUI thread
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.finished.connect(thread.quit)
    thread.start()
    loop.exec()
    thread.wait()
    dialog.close()


if __name__ == "__main__":
    raise SystemExit(main())
