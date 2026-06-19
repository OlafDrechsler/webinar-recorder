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

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QMessageBox,
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
from core.slide_timeline import slide_for_second
from gui.branding import APP_NAME, app_icon
from gui.icons import pause_icon, play_icon, skip_back_icon, skip_forward_icon
from gui.work_area import WorkAreaWindow

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


_TRANSPORT_BTN = (
    "QPushButton{background:#2a2a2a;border:none;border-radius:6px;padding:4px 12px;}"
    "QPushButton:hover{background:#3a3a3a;}"
)


def _round_style(diameter: int) -> str:
    return (
        "QPushButton{background:rgba(20,20,20,170);border:none;border-radius:%dpx;}"
        "QPushButton:hover{background:rgba(60,60,60,205);}" % (diameter // 2)
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
        self._back = QPushButton()
        self._play = QPushButton()
        self._fwd = QPushButton()
        for b, d in ((self._back, 64), (self._play, 84), (self._fwd, 64)):
            b.setFixedSize(d, d)
            b.setStyleSheet(_round_style(d))
        self._back.setIcon(skip_back_icon(36))
        self._back.setIconSize(QSize(40, 40))
        self._fwd.setIcon(skip_forward_icon(36))
        self._fwd.setIconSize(QSize(40, 40))
        self._play.setIconSize(QSize(48, 48))
        self.set_playing(False)
        self._back.clicked.connect(self.back.emit)
        self._play.clicked.connect(self.play_pause.emit)
        self._fwd.clicked.connect(self.forward.emit)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._back)
        row.addSpacing(28)
        row.addWidget(self._play)
        row.addSpacing(28)
        row.addWidget(self._fwd)
        row.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def set_playing(self, playing: bool) -> None:
        self._play.setIcon(pause_icon(48) if playing else play_icon(48))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.background_clicked.emit()


class SlideLabel(QLabel):
    """Big slide view: scales its image, hosts the overlay, turns clicks into
    transport actions (single = play/pause, double left/right = skip)."""

    clicked = Signal()
    seek_back = Signal()
    seek_forward = Signal()
    hold_start = Signal()   # mouse held down -> fast preview
    hold_end = Signal()

    def __init__(self) -> None:
        super().__init__("Kein Ordner geladen")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 240)  # allow the window to be dragged fairly small
        self.setStyleSheet("background:#161616;color:#888;")
        self._single = QTimer(self)
        self._single.setSingleShot(True)
        self._single.setInterval(max(200, QApplication.doubleClickInterval()))
        self._single.timeout.connect(self.clicked.emit)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(220)
        self._hold.timeout.connect(self._begin_hold)
        self._holding = False
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

    def _begin_hold(self) -> None:
        self._holding = True
        self.hold_start.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._single.stop()
        self._hold.start()  # if still down after the interval -> fast preview

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._hold.stop()
        if self._holding:
            self._holding = False
            self.hold_end.emit()
        else:
            self._single.start()  # a tap: disambiguate from a double click

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._single.stop()
        self._hold.stop()
        self._holding = False
        if event.position().x() < self.width() / 2:
            self.seek_back.emit()
        else:
            self.seek_forward.emit()


class _Cell(QWidget):
    """One film-strip thumbnail with its filename underneath; clickable."""

    clicked = Signal(int)
    context = Signal(int)

    def __init__(self, index: int, pixmap: QPixmap | None, caption_text: str, current: bool) -> None:
        super().__init__()
        self._index = index
        thumb = QLabel()
        thumb.setFixedSize(FilmstripBar.THUMB_W, FilmstripBar.THUMB_H)
        thumb.setAlignment(Qt.AlignCenter)
        border = "#2da6ff" if current else "#333"
        thumb.setStyleSheet(f"background:#0e0e0e;border:2px solid {border};")
        if pixmap is not None:
            thumb.setPixmap(pixmap)
        caption = QLabel(caption_text)
        caption.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        caption.setWordWrap(True)
        caption.setStyleSheet("color:#aaa;font-size:10px;")
        caption.setFixedWidth(FilmstripBar.THUMB_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(thumb)
        lay.addWidget(caption)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.context.emit(self._index)
        else:
            self.clicked.emit(self._index)


class _Empty(QWidget):
    """Blank placeholder for film-strip edges (no frame on that side yet)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(FilmstripBar.THUMB_W)


class FilmstripBar(QWidget):
    """Horizontal strip of thumbnails, current centred, empty slots at the edges."""

    frame_clicked = Signal(int)
    frame_context = Signal(int)
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
        self.setFixedHeight(self.THUMB_H + 40)  # room for a two-line caption

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 40)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 40)

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
            caption = f"{frame.name} - {_fmt(frame.second * 1000)}"
            cell = _Cell(idx, self._thumb(frame.name), caption, idx == self._current)
            cell.clicked.connect(self.frame_clicked.emit)
            cell.context.connect(self.frame_context.emit)
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
        self._editor: WorkAreaWindow | None = None

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
        self._slide.hold_start.connect(self._hold_start)
        self._slide.hold_end.connect(self._hold_end)
        self._hold_prev_rate = 1.0
        self._hold_prev_playing = False
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
        self._filmstrip.frame_context.connect(self._show_frame_menu)

        # --- transport ---
        self._back_btn = QPushButton()
        self._back_btn.setIcon(skip_back_icon(26))      # circular "10" arrow, like the overlay
        self._back_btn.setToolTip("10 s zurück")
        self._back_btn.clicked.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._play_btn = QPushButton()
        self._play_btn.setIcon(play_icon(22))
        self._play_btn.clicked.connect(self._toggle_play)
        self._fwd_btn = QPushButton()
        self._fwd_btn.setIcon(skip_forward_icon(26))
        self._fwd_btn.setToolTip("10 s vor")
        self._fwd_btn.clicked.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        for b in (self._back_btn, self._play_btn, self._fwd_btn):
            b.setStyleSheet(_TRANSPORT_BTN)
            b.setIconSize(QSize(26, 26))

        self._slider = QSlider(Qt.Horizontal)
        self._slider.sliderMoved.connect(self._seek)
        self._time = QLabel("00:00 / 00:00")
        self._speed = QComboBox()
        for pct in speed_percent_values():
            self._speed.addItem(f"{pct} %", pct)
        self._speed.setCurrentText("100 %")
        self._speed.currentIndexChanged.connect(self._on_speed)

        self._note_btn = QPushButton("Notiz")
        self._note_btn.setStyleSheet(_TRANSPORT_BTN + "QPushButton{color:white;}")
        self._note_btn.setToolTip("Aktuelle Folie pausieren und annotieren (wird im Filmstreifen abgelegt)")
        self._note_btn.clicked.connect(self._open_editor)

        controls = QHBoxLayout()
        controls.addWidget(self._back_btn)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._fwd_btn)
        controls.addWidget(self._slider, stretch=1)
        controls.addWidget(self._time)
        controls.addWidget(QLabel("Tempo:"))
        controls.addWidget(self._speed)
        controls.addWidget(self._note_btn)

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

        # Mic-segment list with jump-to: a button whose menu lists each segment's
        # start time (mm:ss); choosing one seeks there and plays.
        self._seg_btn = QPushButton("Mikro-Segmente: 0")
        self._seg_btn.setStyleSheet(
            "QPushButton{color:white;background:#2a2a2a;border:none;border-radius:6px;padding:4px 10px;}"
        )
        self._seg_menu = QMenu(self._seg_btn)
        self._seg_btn.setMenu(self._seg_menu)
        seg_row = QHBoxLayout()
        seg_row.addStretch(1)
        seg_row.addWidget(self._seg_btn)

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
        self._frames = build_filmstrip(names)
        # Timeline includes the annotated frames too, so a note is shown as the
        # big image when playback reaches its second (it sorts after the auto
        # frame of the same second, so the note takes precedence there).
        self._timeline = [(f.second, f.name) for f in self._frames]
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
        self._rebuild_segment_menu()
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

    # ----- annotate while watching -----
    def _open_editor(self) -> None:
        """Pause and open the annotation editor on the current slide; the note is
        tagged with the current playback second and saved into the folien folder."""
        if self._slides_dir is None or self._current_slide is None:
            return
        if self._is_playing():
            self._toggle_play()
        second = int(self._system.position() // 1000)
        try:
            frame = np.asarray(Image.open(self._slides_dir / self._current_slide).convert("RGB"))
        except OSError:
            return
        self._editor = WorkAreaWindow(frame, second, self._slides_dir)
        self._editor.setWindowIcon(app_icon())
        self._editor.saved.connect(self._on_note_saved)
        self._editor.show()

    def _on_note_saved(self, name: str) -> None:
        self._refresh_frames()
        self.show_slide(name)  # show the freshly saved note/edit as the big image

    # ----- film-strip context menu -----
    def _show_frame_menu(self, index: int) -> None:
        menu = QMenu(self)
        act_edit = menu.addAction("Bearbeiten")
        act_del = menu.addAction("Löschen")
        chosen = menu.exec(QCursor.pos())
        if chosen == act_edit:
            self._edit_frame(index)
        elif chosen == act_del:
            self._delete_frame(index)

    def _edit_frame(self, index: int) -> None:
        """Edit the clicked image in place (overwrites the same file)."""
        if self._slides_dir is None:
            return
        frame = self._frames[index]
        if self._is_playing():
            self._toggle_play()
        try:
            img = np.asarray(Image.open(self._slides_dir / frame.name).convert("RGB"))
        except OSError:
            return
        self._editor = WorkAreaWindow(img, frame.second, self._slides_dir, save_as=frame.name)
        self._editor.setWindowIcon(app_icon())
        self._editor.saved.connect(self._on_note_saved)
        self._editor.show()

    def _delete_frame(self, index: int) -> None:
        if self._slides_dir is None:
            return
        frame = self._frames[index]
        if QMessageBox.question(
            self, "Bild löschen?", f"'{frame.name}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            (self._slides_dir / frame.name).unlink()
        except OSError:
            pass
        was_current = frame.name == self._current_slide
        self._refresh_frames()
        if was_current:
            self._current_slide = None
            self._update_slide(int(self._system.position() // 1000))
            if self._current_slide is None and self._frames:
                self.show_slide(self._frames[0].name)

    def _refresh_frames(self) -> None:
        """Rebuild timeline + film strip after a note was saved, keeping position."""
        if self._slides_dir is None:
            return
        names = [p.name for p in self._slides_dir.glob("*.png")]
        self._frames = build_filmstrip(names)
        self._timeline = [(f.second, f.name) for f in self._frames]
        self._index_of = {f.name: i for i, f in enumerate(self._frames)}
        self._filmstrip.set_session(self._slides_dir, self._frames)
        if self._current_slide in self._index_of:
            self._filmstrip.set_current(self._index_of[self._current_slide])

    # ----- transport -----
    def _is_playing(self) -> bool:
        return self._system.playbackState() == QMediaPlayer.PlayingState

    def _update_play_icons(self, playing: bool) -> None:
        self._play_btn.setIcon(pause_icon(22) if playing else play_icon(22))
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

    def _apply_rate(self, rate: float) -> None:
        self._system.setPlaybackRate(rate)
        for seg in self._segments:
            seg.player.setPlaybackRate(rate)

    def _on_speed(self) -> None:
        self._rate = self._speed.currentData() / 100.0
        self._apply_rate(self._rate)

    # ----- press-and-hold fast preview (2x) -----
    def _hold_start(self) -> None:
        self._hold_prev_rate = self._rate
        self._hold_prev_playing = self._is_playing()
        if not self._is_playing():
            self._toggle_play()
        self._apply_rate(2.0)

    def _hold_end(self) -> None:
        self._apply_rate(self._hold_prev_rate)
        if not self._hold_prev_playing and self._is_playing():
            self._toggle_play()

    def _on_duration(self, ms: int) -> None:
        self._slider.setRange(0, ms)

    def _on_position(self, ms: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.setValue(ms)
        self._time.setText(f"{_fmt(ms)} / {_fmt(self._system.duration())}")
        self._time.setToolTip(f"{ms // 1000} s")  # current time in seconds
        self._update_slide(ms // 1000)
        self._sync_segments(ms)

    # ----- mic segment list / jump -----
    def _rebuild_segment_menu(self) -> None:
        self._seg_menu.clear()
        self._seg_btn.setText(f"Mikro-Segmente: {len(self._segments)}")
        self._seg_btn.setEnabled(bool(self._segments))
        for seg in sorted(self._segments, key=lambda s: s.start_ms):
            act = self._seg_menu.addAction(_fmt(seg.start_ms))
            act.triggered.connect(lambda _=False, s=seg: self._jump_to_segment(s))

    def _jump_to_segment(self, seg: "MicSegment") -> None:
        self._seek(seg.start_ms)
        if not self._is_playing():
            self._toggle_play()

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
