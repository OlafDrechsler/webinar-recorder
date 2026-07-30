"""Always-on-top control window and the 1 Hz screenshot loop.

Flow: the window opens first WITHOUT recording, so the user can drag it aside and
pick the slide region. Recording (system audio + mic + screenshots) only begins
when "Aufnahme starten" is clicked; the shared start time t0 is set at that
moment so audio and slide filenames line up. The same button then reads
"Aufnahme beenden" and stops/finishes the recording.

Controls:
* Aufnahme starten / beenden (the main toggle)
* Aufnahmebereich wählen / neu wählen
* Foto-Aufnahme an/aus (pauses the screenshot loop, e.g. during group work)
* Bild bearbeiten (freeze current frame into the work area for annotation)
* Mikro-Override (force a mic segment on/off regardless of auto-detection)
* Mikro-Pegel-Test (calibrate the voice-activation threshold)

The screenshot loop runs on a Qt timer in the GUI thread (mss grabs are fast
and mss is not thread-safe), feeding frames through CaptureState so only
changed slides are saved.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.capture_state import CaptureState
from core.i18n import tr
from core.naming import auto_frame_name
from core.settings import get_data_dir, set_data_dir
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_save_discard_cancel, ask_yes_no
from gui.mic_test import MicLevelWindow
from gui.region_selector import select_region
from gui.work_area import WorkAreaWindow
from io_adapters.audio import SegmentedMicRecorder, SystemAudioRecorder
from io_adapters.screen import Region, ScreenCapturer


class _Hotkeys(QObject):
    """Bridges background keyboard hooks onto the GUI thread via signals."""

    toggle_photo = Signal()
    highlight = Signal()
    toggle_mic_override = Signal()

    def register(self) -> bool:
        try:
            import keyboard
        except Exception:
            return False
        try:
            keyboard.add_hotkey("ctrl+alt+p", self.toggle_photo.emit)
            keyboard.add_hotkey("ctrl+alt+h", self.highlight.emit)
            keyboard.add_hotkey("ctrl+alt+m", self.toggle_mic_override.emit)
            return True
        except Exception:
            return False


class ControlWindow(QWidget):
    def __init__(self, mic_device: str | None, on_process) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – {tr('hub.record')}")
        self.setWindowIcon(app_icon())
        # Stay on top, but a normal top-level window (not Qt.Tool) so it shows in
        # the taskbar and can be reached with Alt+Tab.
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        # Storage base + recorders are owned here. The session folder and the
        # system recorder are created when recording starts; the mic recorder runs
        # in monitor mode beforehand (for the level test).
        self._base = get_data_dir()
        self._on_process = on_process  # called(system_wav, segments) after stop
        self._system: SystemAudioRecorder | None = None
        self._mic = SegmentedMicRecorder(self._base, 0.0, device_name=mic_device)
        self._system_wav: Path | None = None
        self._session: Path | None = None  # set when recording starts (for discard)
        self._slides_dir: Path | None = None
        self._start: float | None = None  # set when recording starts
        self._recording = False
        self._abort = False     # discard intent (abort button or X-dialog "discard")
        self._stopping = False  # save intent (the "Aufnahme beenden" button)
        self._capturer = ScreenCapturer()
        self._state = CaptureState()
        self._region: Region | None = None
        self._photo_on = True
        self._mic_mode = "auto"   # "an" / "aus" / "auto" via radio buttons
        self._work_area: WorkAreaWindow | None = None
        self._mic_test: MicLevelWindow | None = None

        # --- UI ---
        # Folder picker in the header (like the player) — no separate dialog.
        self._path_lbl = QLabel(self._base.name)
        self._path_lbl.setToolTip(str(self._base))
        self._path_lbl.setStyleSheet("color:#888;")
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._folder_btn = QPushButton(tr("player.choose_folder_btn"))
        self._folder_btn.clicked.connect(self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("record.storage_label")))
        folder_row.addWidget(self._path_lbl, stretch=1)
        folder_row.addWidget(self._folder_btn)

        # The main start/stop toggle sits on top and is visually prominent.
        self._record_btn = QPushButton(tr("record.start"))
        self._record_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._record_btn.clicked.connect(self._toggle_recording)
        # Discard the running recording without any post-processing; only usable
        # while recording, so it starts disabled.
        self._abort_btn = QPushButton(tr("record.abort"))
        self._abort_btn.setStyleSheet("color: #c0392b; padding: 4px;")
        self._abort_btn.setEnabled(False)
        self._abort_btn.clicked.connect(self._abort_recording)
        self._region_btn = QPushButton(tr("record.region_choose"))
        self._region_btn.clicked.connect(self._reselect_region)
        self._photo_btn = QPushButton()
        self._photo_btn.clicked.connect(self._toggle_photo)
        mark_btn = QPushButton(tr("record.edit_image"))
        mark_btn.clicked.connect(self._open_work_area)
        mic_test_btn = QPushButton(tr("mic.level_test"))
        mic_test_btn.clicked.connect(self._open_mic_test)

        # Mic mode as a three-way radio: an / aus / auto.
        self._rb_on = QRadioButton(tr("mic.on"))
        self._rb_off = QRadioButton(tr("mic.off"))
        self._rb_auto = QRadioButton(tr("mic.auto"))
        self._mic_group = QButtonGroup(self)
        for rb in (self._rb_on, self._rb_off, self._rb_auto):
            self._mic_group.addButton(rb)
        self._rb_auto.setChecked(True)  # set BEFORE connecting, so no early callback
        self._rb_on.toggled.connect(lambda on: on and self._set_mic_mode("on"))
        self._rb_off.toggled.connect(lambda on: on and self._set_mic_mode("off"))
        self._rb_auto.toggled.connect(lambda on: on and self._set_mic_mode("auto"))

        self._status = QLabel()
        self._mic_status = QLabel()

        row1 = QHBoxLayout()
        row1.addWidget(self._region_btn)
        row1.addWidget(self._photo_btn)
        row2 = QHBoxLayout()
        row2.addWidget(mark_btn)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel(tr("mic.label")))
        row3.addWidget(self._rb_on)
        row3.addWidget(self._rb_off)
        row3.addWidget(self._rb_auto)
        row3.addStretch(1)
        row3.addWidget(mic_test_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(folder_row)
        layout.addWidget(self._record_btn)
        layout.addWidget(self._abort_btn)
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addLayout(row3)
        layout.addWidget(self._status)
        layout.addWidget(self._mic_status)

        # Run the mic in monitor mode right away so the Mikro-Pegel-Test works
        # before recording starts (it measures the level but writes no segments).
        try:
            self._mic.start_monitor()
        except Exception:
            pass

        self._refresh_labels()

        # --- hotkeys ---
        self._hotkeys = _Hotkeys()
        self._hotkeys.toggle_photo.connect(self._toggle_photo)
        self._hotkeys.highlight.connect(self._open_work_area)
        self._hotkeys.toggle_mic_override.connect(self._cycle_mic_mode)
        self._hotkeys_ok = self._hotkeys.register()

        # --- timers ---
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_labels)
        self._status_timer.start(500)

    # ----- folder selection (in-window) -----
    def _choose_folder(self) -> None:
        if self._recording:
            return  # don't move the target mid-recording
        chosen = QFileDialog.getExistingDirectory(self, tr("storage.choose_folder"), str(self._base))
        if chosen:
            self._base = Path(chosen)
            set_data_dir(self._base)
            self._path_lbl.setText(self._base.name)
            self._path_lbl.setToolTip(str(self._base))

    # ----- recording start/stop -----
    def _toggle_recording(self) -> None:
        if not self._recording:
            self._start_recording()
        else:
            self._stopping = True  # deliberate "stop & save"; closeEvent skips the X-dialog
            self.close()  # closeEvent stops recorders and runs post-processing

    def _abort_recording(self) -> None:
        # Discard the running recording: no post-processing, delete the whole session.
        if not self._recording:
            return
        if not ask_yes_no(self, tr("record.abort_title"), tr("record.abort_text")):
            return
        self._abort = True
        self.close()  # closeEvent stops recorders, skips processing, removes the folder

    def _start_recording(self) -> None:
        # Create the session folder under the chosen base now, then start. t0 is
        # set here so audio and slide filenames share the same origin; the mic is
        # already monitoring, enable_recording flips it to writing without a gap.
        stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
        session = self._base / f"Webinar_{stamp}"
        self._session = session
        self._slides_dir = session / "folien"
        mic_dir = session / "mikro"
        self._slides_dir.mkdir(parents=True, exist_ok=True)
        mic_dir.mkdir(parents=True, exist_ok=True)
        self._system_wav = session / "system.wav"

        self._system = SystemAudioRecorder(self._system_wav)
        self._mic.set_out_dir(mic_dir)
        self._start = time.monotonic()
        self._system.start()
        self._mic.enable_recording(self._start)
        self._recording = True
        self._record_btn.setText(tr("record.stop"))
        self._abort_btn.setEnabled(True)  # discard available while recording
        self._folder_btn.setEnabled(False)  # locked once recording
        self._refresh_labels()

    # ----- toggles -----
    def _toggle_photo(self) -> None:
        self._photo_on = not self._photo_on
        self._refresh_labels()

    def _set_mic_mode(self, mode: str) -> None:
        self._mic_mode = mode
        self._mic.set_mic_mode(mode)
        self._refresh_labels()

    def _cycle_mic_mode(self) -> None:
        # Hotkey ctrl+alt+m cycles auto -> an -> aus -> auto (updates the radios).
        order = ["auto", "on", "off"]
        nxt = order[(order.index(self._mic_mode) + 1) % len(order)]
        {"auto": self._rb_auto, "on": self._rb_on, "off": self._rb_off}[nxt].setChecked(True)

    def _refresh_labels(self) -> None:
        self._photo_btn.setText(
            f"{tr('record.photo')}: {tr('common.on') if self._photo_on else tr('common.off')}"
        )
        hk = tr("record.hotkeys_on") if getattr(self, "_hotkeys_ok", False) else tr("record.hotkeys_off")
        saved = len(list(self._slides_dir.glob("*.png"))) if self._slides_dir else 0
        region = tr("record.region_none") if self._region is None else tr("record.region_set")
        rec = tr("record.rec_running") if self._recording else tr("record.rec_idle")
        self._status.setText(tr("record.status", rec=rec, region=region, count=saved, hk=hk))

        if self._mic_mode == "off":
            text, color = tr("record.mic_off"), "gray"
        elif self._mic_mode == "on":
            text = tr("record.mic_on_recording") if self._recording else tr("record.mic_on_idle")
            color = "red" if self._recording else "gray"
        else:  # auto
            if not self._recording:
                text, color = tr("record.mic_auto_idle"), "gray"
            elif self._mic.is_active:
                text, color = tr("record.mic_auto_active"), "red"
            else:
                text, color = tr("record.mic_auto_wait"), "gray"
        self._mic_status.setText(text)
        self._mic_status.setStyleSheet(f"color: {color};")

    # ----- capture loop -----
    def _seconds(self) -> int:
        return int(time.monotonic() - self._start)

    def _tick(self) -> None:
        if not self._recording or not self._photo_on or self._region is None:
            return
        frame = self._capturer.grab(self._region)
        if self._state.consider(frame):
            name = auto_frame_name(self._seconds())
            from PIL import Image

            Image.fromarray(frame).save(self._slides_dir / name)

    # ----- actions -----
    def _open_work_area(self) -> None:
        # Works as soon as a region is set — even before recording starts. Once
        # recording runs the image is tagged with seconds-since-start; before
        # that there is no timeline yet, so it is tagged second 0.
        if self._region is None:
            return
        seconds = self._seconds() if self._recording else 0
        frame = self._capturer.grab(self._region)  # fresh grab at click moment
        self._work_area = WorkAreaWindow(frame, seconds, self._slides_dir)
        self._work_area.show()

    def _open_mic_test(self) -> None:
        self._mic_test = MicLevelWindow(self._mic)
        self._mic_test.show()

    def _reselect_region(self) -> None:
        self.hide()
        region = select_region()
        self.show()
        self.activateWindow()
        self.raise_()
        if region is not None:
            self._region = region
            self._state.reset()  # dimensions changed; force next save
            self._region_btn.setText(tr("record.region_rechoose"))
            self._refresh_labels()

    # ----- shutdown -----
    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing via the window's X while recording (neither button was used): ask
        # what to do before stopping anything, so "keep recording" leaves it running.
        if self._recording and not self._stopping and not self._abort:
            choice = ask_save_discard_cancel(
                self, tr("record.close_title"), tr("record.close_text")
            )
            if choice == "cancel":
                event.ignore()
                return
            if choice == "discard":
                self._abort = True
            # "save" -> fall through to the normal stop & post-process path

        self._timer.stop()
        self._status_timer.stop()
        try:
            import keyboard

            keyboard.clear_all_hotkeys()
        except Exception:
            pass
        self._capturer.close()
        self._mic.stop()
        if self._system is not None:
            self._system.stop()
        if self._abort and self._session is not None:
            # Discard: drop the whole session, run no post-processing. Handles are
            # released above; ignore_errors so a lingering lock can't block the close.
            shutil.rmtree(self._session, ignore_errors=True)
        elif self._on_process is not None and self._system_wav is not None and (
            self._system_wav.exists() or self._mic.segments
        ):
            # Post-process (loudness-match + MP3) if a recording was made.
            self._on_process(self._system_wav, self._mic.segments)
        super().closeEvent(event)
