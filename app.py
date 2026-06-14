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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core.loudness import aggregate_mean_db, compute_gain_db
from core.settings import get_mic_device
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


def main() -> int:
    # Use the exact (possibly fractional) display scale so devicePixelRatioF
    # reports e.g. 1.5 on a 150% display — required for the region selector to
    # map its logical rectangle to physical pixels correctly. Must be set before
    # the QApplication is created.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    session = _choose_session(app)
    if session is None:
        return 0
    slides_dir = session / "folien"
    mic_dir = session / "mikro"
    system_wav = session / "system.wav"

    # Recorders are created but NOT started here: the control window opens first
    # so the user can position it and pick the slide region, then starts the
    # recording explicitly. The shared start time t0 is set at that moment (inside
    # the window) so audio and slide filenames line up on seconds-since-start.
    system = SystemAudioRecorder(system_wav)
    mic = SegmentedMicRecorder(mic_dir, 0.0, device_name=get_mic_device())

    window = ControlWindow(system, mic, slides_dir)
    # WA_DeleteOnClose makes closing the window actually destroy it, so the
    # destroyed signal fires and the event loop quits. Without this the window
    # is only hidden (quitOnLastWindowClosed is off), app.exec() never returns,
    # and the WAV->MP3 transcode below would never run.
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.destroyed.connect(app.quit)
    window.show()
    app.exec()

    # If the user never started a recording, there is nothing to process.
    if not system_wav.exists() and not mic.segments:
        print("Keine Aufnahme erstellt.")
        return 0

    # Post-process audio (recorders already stopped in closeEvent): measure each
    # source's loudness, then transcode to MP3 applying a clip-safe gain so the
    # system track and the mic segments end up at a similar volume on playback.
    if ffmpeg_available():
        _normalize_and_transcode(system_wav, mic.segments)
        fmt = "MP3 (lautstärke-angeglichen)"
    else:
        fmt = "WAV (FFmpeg nicht gefunden)"

    print(f"Aufnahme gespeichert in: {session}")
    print(f"Audioformat: {fmt} | Mikro-Segmente: {len(mic.segments)}")
    return 0


def _normalize_and_transcode(system_wav: Path, mic_segments: list[Path]) -> None:
    """Loudness-match system + mic, then transcode all tracks to MP3.

    Loudness is EBU R128 integrated loudness (LUFS), which ignores silence, with
    a true-peak cap so no clipping is introduced. The system track gets its own
    gain. All mic segments share ONE gain (from their combined loudness) so their
    relative dynamics stay intact while their overall loudness matches the system
    track. Measuring happens before transcode because transcode deletes the WAV.
    """
    sys_lufs, sys_tp = measure_loudness(system_wav)
    transcode_to_mp3(system_wav, gain_db=compute_gain_db(sys_lufs, sys_tp))

    if not mic_segments:
        return
    measured = [measure_loudness(seg) for seg in mic_segments]
    mic_lufs = aggregate_mean_db([lufs for lufs, _ in measured])
    peaks = [tp for _, tp in measured if tp is not None]
    mic_tp = max(peaks) if peaks else None
    mic_gain = compute_gain_db(mic_lufs, mic_tp)
    for seg in mic_segments:
        transcode_to_mp3(seg, gain_db=mic_gain)


if __name__ == "__main__":
    raise SystemExit(main())
