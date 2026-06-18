"""Playback for a recorded session.

Plays the system-audio track as the master timeline, mixes in each microphone
segment at its correct start time, and shows the slide that was on screen at
each moment (from the second-offset in each slide filename).

Controls: click the slide = play/pause, double-click its left/right half = skip
10 s back/forward, playback speed 50–200 %, the current slide's filename is shown,
and independent System/Mikro volume sliders (all remembered across sessions).

Run:  python player/play.py [session_folder]
If no folder is given, a folder picker opens.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.mic_playback import parse_segment_start, segment_local_offset
from core.playback import SEEK_STEP_MS, seek_target, speed_percent_values
from core.settings import get_data_dir, get_player_volumes, set_player_volumes
from core.slide_timeline import build_timeline, slide_for_second

# Re-sync a segment if it has drifted from the master by more than this.
_DRIFT_MS = 350


def _find_track(session: Path, stem: str) -> Path | None:
    for ext in (".mp3", ".wav", ".opus"):
        p = session / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def _fmt(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class SlideLabel(QLabel):
    """Slide display that turns clicks into transport actions.

    Single click → play/pause; double click on the left/right half → skip back/
    forward. A short timer disambiguates the two so a double click doesn't also
    fire a single click.
    """

    clicked = Signal()
    seek_back = Signal()
    seek_forward = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._single = QTimer(self)
        self._single.setSingleShot(True)
        self._single.setInterval(max(200, QApplication.doubleClickInterval()))
        self._single.timeout.connect(self.clicked.emit)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._single.start()  # may be cancelled by a following double click

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._single.stop()
        if event.position().x() < self.width() / 2:
            self.seek_back.emit()
        else:
            self.seek_forward.emit()


class MicSegment:
    def __init__(self, start_sec: int, path: Path) -> None:
        self.start_ms = start_sec * 1000
        self.duration = 0
        self.out = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.out)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.durationChanged.connect(self._on_duration)

    def _on_duration(self, ms: int) -> None:
        self.duration = ms


class Player(QWidget):
    def __init__(self, session: Path) -> None:
        super().__init__()
        self.setWindowTitle(f"Wiedergabe – {session.name}")
        self._session = session
        self._slides_dir = session / "folien"
        self._timeline = build_timeline(p.name for p in self._slides_dir.glob("*.png"))
        self._current_slide: str | None = None

        # Remembered playback volumes (percent) for the two sources.
        sys_vol, mic_vol = get_player_volumes()

        # Master = system audio.
        self._system = QMediaPlayer()
        self._system_out = QAudioOutput()
        self._system.setAudioOutput(self._system_out)
        self._system_out.setVolume(sys_vol / 100.0)
        sys_track = _find_track(session, "system")
        if sys_track:
            self._system.setSource(QUrl.fromLocalFile(str(sys_track)))

        # Microphone segments.
        self._segments: list[MicSegment] = []
        mic_dir = session / "mikro"
        if mic_dir.is_dir():
            for p in sorted(mic_dir.glob("mikro_*")):
                start = parse_segment_start(p.name)
                if start is not None:
                    self._segments.append(MicSegment(start, p))
        for seg in self._segments:
            seg.out.setVolume(mic_vol / 100.0)

        # --- UI ---
        self._slide_label = SlideLabel("Keine Folie")
        self._slide_label.setAlignment(Qt.AlignCenter)
        self._slide_label.setMinimumSize(640, 400)
        self._slide_label.setStyleSheet("background:#222;color:#aaa;")
        self._slide_label.setToolTip("Klick = Play/Pause · Doppelklick links/rechts = 10 s zurück/vor")
        self._slide_label.clicked.connect(self._toggle_play)
        self._slide_label.seek_back.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._slide_label.seek_forward.connect(lambda: self._seek_relative(SEEK_STEP_MS))

        self._fname = QLabel("Folie: —")
        self._fname.setStyleSheet("color:#888;")

        self._play_btn = QPushButton("Abspielen")
        self._play_btn.clicked.connect(self._toggle_play)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.sliderMoved.connect(self._seek)
        self._time = QLabel("00:00 / 00:00")
        self._seg_info = QLabel(f"Mikro-Segmente: {len(self._segments)}")

        # Playback speed: 50 %..200 % in 10 % steps.
        self._rate = 1.0
        self._speed = QComboBox()
        for pct in speed_percent_values():
            self._speed.addItem(f"{pct} %", pct)
        self._speed.setCurrentText("100 %")
        self._speed.currentIndexChanged.connect(self._on_speed)

        controls = QHBoxLayout()
        controls.addWidget(self._play_btn)
        controls.addWidget(self._slider)
        controls.addWidget(self._time)
        controls.addWidget(QLabel("Tempo:"))
        controls.addWidget(self._speed)

        # Volume sliders (System + Mikro), each remembered across sessions.
        self._sys_vol = QSlider(Qt.Horizontal)
        self._sys_vol.setRange(0, 100)
        self._sys_vol.setValue(sys_vol)
        self._sys_vol.valueChanged.connect(self._on_system_volume)
        self._sys_vol_lbl = QLabel(f"{sys_vol}%")
        self._mic_vol = QSlider(Qt.Horizontal)
        self._mic_vol.setRange(0, 100)
        self._mic_vol.setValue(mic_vol)
        self._mic_vol.valueChanged.connect(self._on_mic_volume)
        self._mic_vol_lbl = QLabel(f"{mic_vol}%")

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("System:"))
        vol_row.addWidget(self._sys_vol)
        vol_row.addWidget(self._sys_vol_lbl)
        vol_row.addSpacing(16)
        vol_row.addWidget(QLabel("Mikro:"))
        vol_row.addWidget(self._mic_vol)
        vol_row.addWidget(self._mic_vol_lbl)

        layout = QVBoxLayout(self)
        layout.addWidget(self._slide_label, stretch=1)
        layout.addWidget(self._fname)
        layout.addLayout(controls)
        layout.addLayout(vol_row)
        layout.addWidget(self._seg_info)

        self._system.positionChanged.connect(self._on_position)
        self._system.durationChanged.connect(self._on_duration)

    # ----- volume -----
    def _on_system_volume(self, value: int) -> None:
        self._system_out.setVolume(value / 100.0)
        self._sys_vol_lbl.setText(f"{value}%")
        self._persist_volumes()

    def _on_mic_volume(self, value: int) -> None:
        for seg in self._segments:
            seg.out.setVolume(value / 100.0)
        self._mic_vol_lbl.setText(f"{value}%")
        self._persist_volumes()

    def _persist_volumes(self) -> None:
        set_player_volumes(self._sys_vol.value(), self._mic_vol.value())

    # ----- transport -----
    def _is_playing(self) -> bool:
        return self._system.playbackState() == QMediaPlayer.PlayingState

    def _toggle_play(self) -> None:
        if self._is_playing():
            self._system.pause()
            for seg in self._segments:
                seg.player.pause()
            self._play_btn.setText("Abspielen")
        else:
            self._system.play()
            self._play_btn.setText("Pause")
            self._sync_segments(self._system.position())

    def _seek(self, ms: int) -> None:
        self._system.setPosition(ms)
        self._sync_segments(ms)

    def _seek_relative(self, delta_ms: int) -> None:
        target = seek_target(self._system.position(), delta_ms, self._system.duration())
        self._system.setPosition(target)
        self._sync_segments(target)

    def _on_speed(self) -> None:
        self._rate = self._speed.currentData() / 100.0
        self._system.setPlaybackRate(self._rate)
        for seg in self._segments:
            seg.player.setPlaybackRate(self._rate)

    def _on_duration(self, ms: int) -> None:
        self._slider.setRange(0, ms)

    def _on_position(self, ms: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.setValue(ms)
        self._time.setText(f"{_fmt(ms)} / {_fmt(self._system.duration())}")
        self._update_slide(ms // 1000)
        self._sync_segments(ms)

    # ----- mic segment sync -----
    def _sync_segments(self, ms: int) -> None:
        playing = self._is_playing()
        for seg in self._segments:
            local = segment_local_offset(seg.start_ms, seg.duration, ms)
            if local is not None and playing:
                if seg.player.playbackState() != QMediaPlayer.PlayingState:
                    seg.player.setPosition(local)
                    seg.player.play()
                elif abs(seg.player.position() - local) > _DRIFT_MS:
                    seg.player.setPosition(local)
            else:
                if seg.player.playbackState() == QMediaPlayer.PlayingState:
                    seg.player.pause()

    # ----- slides -----
    def _update_slide(self, second: int) -> None:
        name = slide_for_second(self._timeline, second)
        if name and name != self._current_slide:
            self._current_slide = name
            pix = QPixmap(str(self._slides_dir / name))
            self._slide_label.setPixmap(
                pix.scaled(self._slide_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._fname.setText(f"Folie: {name}")


def main() -> int:
    app = QApplication(sys.argv)
    if len(sys.argv) > 1:
        session = Path(sys.argv[1])
    else:
        # Start the picker at the saved recordings location, not the program dir.
        folder = QFileDialog.getExistingDirectory(
            None, "Aufnahme-Ordner wählen", str(get_data_dir())
        )
        if not folder:
            return 0
        session = Path(folder)
    win = Player(session)
    win.resize(800, 640)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
