"""Webinar recorder — entry point.

Continuous system audio + voice-activated microphone segments, plus a 1 Hz
screenshot of a chosen region that is saved only when the slide changes.

Flow:
1. A storage dialog asks where to save (pre-filled with last time's folder,
   persisted via core.settings — typically a OneDrive folder).
2. One session folder ``Webinar_<date>`` is created under the chosen location.
3. The control window opens WITHOUT recording yet, so the user can move it aside
   and pick the slide region.
4. The user clicks "Aufnahme starten" — only now do audio and screenshots begin.
   Clicking the same button again ("Aufnahme beenden") stops and finishes.

Run:  python app.py     (or use the desktop shortcut created by install.ps1)
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog

from core.loudness import aggregate_mean_db, compute_gain_db
from core.settings import get_mic_device
from gui.branding import app_icon
from gui.control_window import ControlWindow
from gui.storage_dialog import StorageDialog
from io_adapters.audio import SegmentedMicRecorder, SystemAudioRecorder
from io_adapters.encode import ffmpeg_available, measure_loudness, transcode_to_mp3


def _session_dir(base: Path) -> Path:
    """Create and return ``<base>/Webinar_<date>`` with its subfolders.

    Raises OSError if ``base`` cannot be written to (handled by the caller, which
    re-opens the storage dialog).
    """
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
    session = Path(base) / f"Webinar_{stamp}"
    (session / "folien").mkdir(parents=True, exist_ok=True)
    (session / "mikro").mkdir(parents=True, exist_ok=True)
    return session


def _choose_session(app: QApplication) -> Path | None:
    """Show the storage dialog and build the session folder.

    Loops if the chosen folder can't be created (e.g. no permission), so the user
    can pick another. Returns the session path, or None if the user cancelled.
    """
    while True:
        dialog = StorageDialog()
        if dialog.exec() != QDialog.Accepted:
            return None
        base = dialog.chosen_path()
        try:
            return _session_dir(base)
        except OSError as exc:
            QMessageBox.warning(
                None,
                "Ordner nicht nutzbar",
                f"Der Ordner konnte nicht angelegt werden:\n{base}\n\n{exc}\n\n"
                "Bitte einen anderen Speicherort wählen.",
            )


def launch_recording() -> ControlWindow | None:
    """Run the storage dialog, create the recorders and show the control window.

    The (threaded) loudness-match + MP3 transcode runs automatically when the
    window is closed. Usable from the hub (no QApplication ownership). Returns the
    control window, or None if the storage dialog was cancelled.
    """
    session = _choose_session(None)
    if session is None:
        return None
    slides_dir = session / "folien"
    mic_dir = session / "mikro"
    system_wav = session / "system.wav"

    # Recorders are created but NOT started here: the control window opens first
    # so the user can position it and pick the slide region, then starts the
    # recording explicitly. The shared start time t0 is set at that moment.
    system = SystemAudioRecorder(system_wav)
    mic = SegmentedMicRecorder(mic_dir, 0.0, device_name=get_mic_device())

    window = ControlWindow(system, mic, slides_dir)
    window.setAttribute(Qt.WA_DeleteOnClose, True)

    def finish() -> None:
        if (system_wav.exists() or mic.segments) and ffmpeg_available():
            _run_postprocessing_with_progress(system_wav, mic.segments)
        print(f"Aufnahme gespeichert in: {session} | Mikro-Segmente: {len(mic.segments)}")

    window.destroyed.connect(finish)
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
    if window is None:
        return 0
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

    step("System-Ton wird umgewandelt…", 0)
    sys_lufs, sys_tp = measure_loudness(system_wav)
    transcode_to_mp3(system_wav, gain_db=compute_gain_db(sys_lufs, sys_tp))

    n = len(mic_segments)
    if n:
        measured = []
        for i, seg in enumerate(mic_segments):
            step(f"Analysiere Mikro-Segment {i + 1}/{n}…", 1)
            measured.append(measure_loudness(seg))
        mic_lufs = aggregate_mean_db([lufs for lufs, _ in measured])
        peaks = [tp for _, tp in measured if tp is not None]
        mic_gain = compute_gain_db(mic_lufs, max(peaks) if peaks else None)
        for i, seg in enumerate(mic_segments):
            step(f"Wandle Mikro-Segment {i + 1}/{n} um…", 1 + i)
            transcode_to_mp3(seg, gain_db=mic_gain)
    step("Fertig.", total)


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
            self.progress.emit(f"Aufnahme wird verarbeitet…\n{label} ({done}/{total})")

        _normalize_and_transcode(self._system_wav, self._segments, progress=report)
        self.finished.emit()


def _run_postprocessing_with_progress(system_wav: Path, segments: list[Path]) -> None:
    # Indeterminate (marquee) progress so it visibly keeps moving during the long
    # system-track transcode; the actual work runs in a worker thread.
    dialog = QProgressDialog("Aufnahme wird verarbeitet…", None, 0, 0)
    dialog.setWindowTitle("Bitte warten")
    dialog.setWindowModality(Qt.ApplicationModal)
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
