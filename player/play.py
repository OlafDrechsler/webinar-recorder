"""Playback for a recorded session (WebinarOD player).

Plays the system-audio track as the master timeline, mixes in each microphone
segment at its correct start time, and shows the slide that was on screen at
each moment. The recording folder is chosen *inside* the window, so you can
switch between webinars without restarting.

Controls:
* Folder picker in the header — switch the played recording any time.
* The first slide is shown immediately, before playback starts.
* Film strip below the image: previous/next slides (incl. annotated ones),
  current one centred and framed, filename under each. Click a thumbnail to jump
  there — the audio (system + the right mic segment) follows.
* Click the big image = play/pause and briefly reveal a controls overlay;
  double-click its left/right half = skip 10 s back/forward.
* Transport buttons (−10 s / play-pause / +10 s), speed 50–200 %, and remembered
  System/Mikro volume sliders.

Run:  python player/play.py [session_folder]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.filmstrip import build_filmstrip, visible_slots
from core.mic_playback import parse_segment_start, segment_local_offset
from core.playback import SEEK_STEP_MS, seek_target, speed_percent_values
from core.settings import get_data_dir, get_player_volumes, set_player_volumes
from core.slide_timeline import build_timeline, slide_for_second
from gui.branding import APP_NAME, app_icon

_DRIFT_MS = 350          # re-sync a mic segment if it drifts more than this
_OVERLAY_MS = 1800       # auto-hide the controls overlay after this


def _find_track(session: Path, stem: str) -> Path | None:
    for ext in (".mp3", ".wav", ".opus"):
        p = session / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def _fmt(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


_OVERLAY_BTN = (
    "QPushButton{background:rgba(20,20,20,160);color:white;border:none;"
    "border-radius:30px;font-size:20px;min-width:60px;min-height:60px;}"
    "QPushButton:hover{background:rgba(60,60,60,190);}"
)
_TRANSPORT_BTN = (
    "QPushButton{background:#2a2a2a;color:white;border:none;border-radius:6px;"
    "padding:4px 12px;}"  # no font-size override -> uses the window's default size
    "QPushButton:hover{background:#3a3a3a;}"
)


class ControlsOverlay(QWidget):
    """Translucent controls shown over the slide on click (transparent backdrop)."""

    background_clicked = Signal()
    back = Signal()
    play_pause = Signal()
    forward = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._back = QPushButton("↺ 10")
        self._play = QPushButton("▶")
        self._fwd = QPushButton("10 ↻")
        for b in (self._back, self._play, self._fwd):
            b.setStyleSheet(_OVERLAY_BTN)
        self._play.setStyleSheet(
            _OVERLAY_BTN.replace("min-width:60px;min-height:60px;", "min-width:76px;min-height:76px;font-size:26px;")
        )
        self._back.clicked.connect(self.back.emit)
        self._play.clicked.connect(self.play_pause.emit)
        self._fwd.clicked.connect(self.forward.emit)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._back)
        row.addSpacing(24)
        row.addWidget(self._play)
        row.addSpacing(24)
        row.addWidget(self._fwd)
        row.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def set_playing(self, playing: bool) -> None:
        self._play.setText("❚❚" if playing else "▶")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.background_clicked.emit()


class SlideLabel(QLabel):
    """Big slide view: scales its image, hosts the overlay, turns clicks into
    transport actions (single = play/pause, double left/right = skip)."""

    clicked = Signal()
    seek_back = Signal()
    seek_forward = Signal()

    def __init__(self) -> None:
        super().__init__("Kein Ordner geladen")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 240)  # allow the window to be dragged fairly small
        self.setStyleSheet("background:#161616;color:#888;")
        self._single = QTimer(self)
        self._single.setSingleShot(True)
        self._single.setInterval(max(200, QApplication.doubleClickInterval()))
        self._single.timeout.connect(self.clicked.emit)
        self._full: QPixmap | None = None
        self.overlay: ControlsOverlay | None = None

    def attach_overlay(self, overlay: ControlsOverlay) -> None:
        self.overlay = overlay
        overlay.setParent(self)
        overlay.hide()

    def set_slide_pixmap(self, full: QPixmap) -> None:
        self._full = full
        self._apply_scaled()

    def _apply_scaled(self) -> None:
        if self._full is not None and not self._full.isNull():
            super().setPixmap(
                self._full.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._apply_scaled()
        if self.overlay is not None:
            self.overlay.setGeometry(self.rect())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._single.start()  # cancelled by a following double click

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._single.stop()
        if event.position().x() < self.width() / 2:
            self.seek_back.emit()
        else:
            self.seek_forward.emit()


class _Cell(QWidget):
    """One film-strip thumbnail with its filename underneath; clickable."""

    clicked = Signal(int)

    def __init__(self, index: int, pixmap: QPixmap | None, name: str, current: bool) -> None:
        super().__init__()
        self._index = index
        thumb = QLabel()
        thumb.setFixedSize(FilmstripBar.THUMB_W, FilmstripBar.THUMB_H)
        thumb.setAlignment(Qt.AlignCenter)
        border = "#2da6ff" if current else "#333"
        thumb.setStyleSheet(f"background:#0e0e0e;border:2px solid {border};")
        if pixmap is not None:
            thumb.setPixmap(pixmap)
        caption = QLabel(name)
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet("color:#aaa;font-size:10px;")
        caption.setFixedWidth(FilmstripBar.THUMB_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(thumb)
        lay.addWidget(caption)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self._index)


class _Empty(QWidget):
    """Blank placeholder for film-strip edges (no frame on that side yet)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(FilmstripBar.THUMB_W)


class FilmstripBar(QWidget):
    """Horizontal strip of thumbnails, current centred, empty slots at the edges."""

    frame_clicked = Signal(int)
    THUMB_W = 140
    THUMB_H = 84
    GAP = 8

    def __init__(self) -> None:
        super().__init__()
        self._slides_dir: Path | None = None
        self._frames: list = []
        self._current = 0
        self._cache: dict[str, QPixmap] = {}
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 4, 6, 4)
        self._row.setSpacing(self.GAP)
        self._row.setAlignment(Qt.AlignHCenter)
        # Don't let the strip dictate a minimum window width: it must be able to
        # shrink (showing fewer thumbnails) when the window is made narrower.
        self._row.setSizeConstraint(QLayout.SetNoConstraint)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(self.THUMB_H + 24)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 24)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 24)

    def set_session(self, slides_dir: Path, frames: list) -> None:
        self._slides_dir = slides_dir
        self._frames = frames
        self._current = 0
        self._cache.clear()
        self._rebuild()

    def set_current(self, index: int) -> None:
        if index != self._current:
            self._current = index
            self._rebuild()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._rebuild()

    def _slot_count(self) -> int:
        per = self.THUMB_W + self.GAP
        n = max(3, self.width() // per)
        return n if n % 2 == 1 else n - 1  # force odd so there is a middle

    def _thumb(self, name: str) -> QPixmap | None:
        if name in self._cache:
            return self._cache[name]
        if self._slides_dir is None:
            return None
        pix = QPixmap(str(self._slides_dir / name))
        if pix.isNull():
            return None
        scaled = pix.scaled(self.THUMB_W, self.THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._cache[name] = scaled
        return scaled

    def _clear(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear()
        if not self._frames:
            return
        for idx in visible_slots(len(self._frames), self._current, self._slot_count()):
            if idx is None:
                self._row.addWidget(_Empty())
                continue
            frame = self._frames[idx]
            cell = _Cell(idx, self._thumb(frame.name), frame.name, idx == self._current)
            cell.clicked.connect(self.frame_clicked.emit)
            self._row.addWidget(cell)


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

    def dispose(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())


class Player(QWidget):
    def __init__(self, session: Path | None = None) -> None:
        super().__init__()
        self.setWindowIcon(app_icon())
        self.setWindowTitle(APP_NAME)

        sys_vol, mic_vol = get_player_volumes()
        self._rate = 1.0
        self._slides_dir: Path | None = None
        self._timeline: list = []
        self._frames: list = []
        self._index_of: dict[str, int] = {}
        self._current_slide: str | None = None
        self._segments: list[MicSegment] = []

        # Master = system audio (persists across folder switches).
        self._system = QMediaPlayer()
        self._system_out = QAudioOutput()
        self._system.setAudioOutput(self._system_out)
        self._system_out.setVolume(sys_vol / 100.0)

        # --- header: folder picker ---
        self._path_lbl = QLabel("(kein Ordner geladen)")
        self._path_lbl.setStyleSheet("color:#888;")
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        choose = QPushButton("Ordner wählen…")
        choose.clicked.connect(self._choose_folder)
        header = QHBoxLayout()
        header.addWidget(QLabel("Ordner:"))
        header.addWidget(self._path_lbl, stretch=1)
        header.addWidget(choose)

        # --- big slide + overlay ---
        self._slide = SlideLabel()
        self._overlay = ControlsOverlay()
        self._slide.attach_overlay(self._overlay)
        self._slide.clicked.connect(self._on_image_click)
        self._slide.seek_back.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._slide.seek_forward.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        self._overlay.background_clicked.connect(self._on_image_click)
        self._overlay.back.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._overlay.forward.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        self._overlay.play_pause.connect(self._toggle_play)
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._overlay.hide)

        self._fname = QLabel("Folie: —")
        self._fname.setStyleSheet("color:#888;")

        self._filmstrip = FilmstripBar()
        self._filmstrip.frame_clicked.connect(self._on_frame_clicked)

        # --- transport ---
        self._back_btn = QPushButton("↺ 10")
        self._back_btn.clicked.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._play_btn = QPushButton("▶")
        self._play_btn.clicked.connect(self._toggle_play)
        self._fwd_btn = QPushButton("10 ↻")
        self._fwd_btn.clicked.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        for b in (self._back_btn, self._play_btn, self._fwd_btn):
            b.setStyleSheet(_TRANSPORT_BTN)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.sliderMoved.connect(self._seek)
        self._time = QLabel("00:00 / 00:00")
        self._speed = QComboBox()
        for pct in speed_percent_values():
            self._speed.addItem(f"{pct} %", pct)
        self._speed.setCurrentText("100 %")
        self._speed.currentIndexChanged.connect(self._on_speed)

        controls = QHBoxLayout()
        controls.addWidget(self._back_btn)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._fwd_btn)
        controls.addWidget(self._slider, stretch=1)
        controls.addWidget(self._time)
        controls.addWidget(QLabel("Tempo:"))
        controls.addWidget(self._speed)

        # --- volume ---
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

        self._seg_info = QLabel("Mikro-Segmente: 0")
        self._seg_info.setAlignment(Qt.AlignRight)
        seg_row = QHBoxLayout()
        seg_row.addStretch(1)
        seg_row.addWidget(self._seg_info)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._slide, stretch=1)
        layout.addWidget(self._fname)
        layout.addWidget(self._filmstrip)
        layout.addLayout(controls)
        layout.addLayout(vol_row)
        layout.addLayout(seg_row)

        self._system.positionChanged.connect(self._on_position)
        self._system.durationChanged.connect(self._on_duration)

        if session is not None:
            self.load_session(session)

    # ----- session loading -----
    def _choose_folder(self) -> None:
        start = str(self._slides_dir.parent if self._slides_dir else get_data_dir())
        folder = QFileDialog.getExistingDirectory(self, "Aufnahme-Ordner wählen", start)
        if folder:
            self.load_session(Path(folder))

    def load_session(self, session: Path) -> None:
        self._system.stop()
        for seg in self._segments:
            seg.dispose()
        self._segments = []

        self._slides_dir = session / "folien"
        names = [p.name for p in self._slides_dir.glob("*.png")] if self._slides_dir.is_dir() else []
        self._timeline = build_timeline(names)
        self._frames = build_filmstrip(names)
        self._index_of = {f.name: i for i, f in enumerate(self._frames)}
        self._current_slide = None

        sys_track = _find_track(session, "system")
        self._system.setSource(QUrl.fromLocalFile(str(sys_track)) if sys_track else QUrl())
        self._system.setPlaybackRate(self._rate)

        mic_dir = session / "mikro"
        if mic_dir.is_dir():
            for p in sorted(mic_dir.glob("mikro_*")):
                start = parse_segment_start(p.name)
                if start is not None:
                    self._segments.append(MicSegment(start, p))
        mic_vol = self._mic_vol.value() / 100.0
        for seg in self._segments:
            seg.out.setVolume(mic_vol)
            seg.player.setPlaybackRate(self._rate)

        self.setWindowTitle(f"{APP_NAME} – {session.name}")
        # Show just the folder name (full path as tooltip) so a long path doesn't
        # force a wide minimum window size.
        self._path_lbl.setText(session.name)
        self._path_lbl.setToolTip(str(session))
        self._seg_info.setText(f"Mikro-Segmente: {len(self._segments)}")
        self._slider.setValue(0)
        self._time.setText("00:00 / 00:00")
        self._filmstrip.set_session(self._slides_dir, self._frames)
        self._update_play_icons(False)

        # Show the first slide immediately (lowest number, may be > 0).
        if self._frames:
            self.show_slide(self._frames[0].name)
        else:
            self._slide.setText("Keine Folien in diesem Ordner")
            self._fname.setText("Folie: —")

    # ----- slides -----
    def show_slide(self, name: str) -> None:
        if self._slides_dir is None:
            return
        self._current_slide = name
        self._slide.set_slide_pixmap(QPixmap(str(self._slides_dir / name)))
        self._fname.setText(f"Folie: {name}")
        if name in self._index_of:
            self._filmstrip.set_current(self._index_of[name])

    def _update_slide(self, second: int) -> None:
        name = slide_for_second(self._timeline, second)
        if name and name != self._current_slide:
            self.show_slide(name)

    def _on_frame_clicked(self, index: int) -> None:
        frame = self._frames[index]
        self.show_slide(frame.name)
        self._seek(frame.second * 1000)

    # ----- transport -----
    def _is_playing(self) -> bool:
        return self._system.playbackState() == QMediaPlayer.PlayingState

    def _update_play_icons(self, playing: bool) -> None:
        self._play_btn.setText("❚❚" if playing else "▶")
        self._overlay.set_playing(playing)

    def _toggle_play(self) -> None:
        if self._is_playing():
            self._system.pause()
            for seg in self._segments:
                seg.player.pause()
            self._update_play_icons(False)
        else:
            self._system.play()
            self._update_play_icons(True)
            self._sync_segments(self._system.position())

    def _on_image_click(self) -> None:
        self._toggle_play()
        self._overlay.setGeometry(self._slide.rect())
        self._overlay.raise_()
        self._overlay.show()
        self._overlay_timer.start(_OVERLAY_MS)

    def _seek(self, ms: int) -> None:
        self._system.setPosition(ms)
        self._sync_segments(ms)

    def _seek_relative(self, delta_ms: int) -> None:
        target = seek_target(self._system.position(), delta_ms, self._system.duration())
        self._seek(target)
        self._overlay_timer.start(_OVERLAY_MS)  # keep overlay visible while skipping

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


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    session = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    win = Player(session)
    win.resize(960, 760)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
