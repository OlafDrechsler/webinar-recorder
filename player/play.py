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

import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QObject, QSize, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.filmstrip import build_filmstrip, visible_slots
from core.i18n import tr
from core.mic_playback import parse_segment_start, segment_local_offset
from core.playback import SEEK_STEP_MS, seek_target, speed_percent_values
from core.settings import get_data_dir, get_player_volumes, set_player_volumes
from core.slide_timeline import slide_for_second
from io_adapters.encode import trim_audio
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_yes_no
from gui.slide_ops import adjust_slide_time, delete_slide, move_slide
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


def _wait_file_writable(path: Path, tries: int = 80) -> bool:
    """Retry until ``path`` is no longer locked by a media player, or time out.

    Used from a worker thread (no Qt calls): the main thread's event loop runs the
    progress dialog and lets Qt release the handle while we poll here."""
    for _ in range(tries):
        try:
            with open(path, "r+b"):
                return True
        except OSError:
            time.sleep(0.025)
    return False


class _DiscardWorker(QObject):
    """Trims the system track and deletes the trailing mic files off the GUI
    thread, so the window stays responsive during the FFmpeg call."""

    finished = Signal()

    def __init__(self, sys_track: Path, end_seconds: float, doomed_paths: list[Path]) -> None:
        super().__init__()
        self._sys_track = sys_track
        self._end_seconds = end_seconds
        self._doomed = doomed_paths

    def run(self) -> None:
        _wait_file_writable(self._sys_track)
        trim_audio(self._sys_track, self._end_seconds)
        for p in self._doomed:
            _wait_file_writable(p)
            try:
                p.unlink()
            except OSError:
                pass
        self.finished.emit()


def merge_strip_items(frames, mics: list[tuple[int, int]]) -> list[dict]:
    """Merge slide frames and mic segments ``(start_ms, end_ms)`` into the ordered
    film-strip item list. A slide sorts before a mic marker of the same second,
    so the marker sits to its right. ``end_ms == start_ms`` means "length not
    known yet" (the caption then shows only the start time)."""
    items: list[dict] = [
        {"kind": "slide", "name": f.name, "second": f.second} for f in frames
    ]
    for start_ms, end_ms in mics:
        items.append({
            "kind": "mic",
            "second": start_ms // 1000,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
    items.sort(key=lambda it: (it["second"], 0 if it["kind"] == "slide" else 1))
    return items


def latest_index_at_or_before(items: list[dict], second: int) -> int | None:
    """Index of the last strip item whose second is <= ``second``, or None when
    ``second`` lies before every item. Items must be sorted ascending by second."""
    idx = None
    for i, it in enumerate(items):
        if it["second"] <= second:
            idx = i
        else:
            break
    return idx


def strip_caption(item: dict) -> str:
    """Caption under a film-strip cell: ``name - mm:ss`` for a slide,
    ``M - start - end`` for a mic marker (only ``M - start`` while loading)."""
    if item["kind"] == "mic":
        start = _fmt(item["start_ms"])
        if item.get("end_ms", 0) > item["start_ms"]:
            return f"M - {start} - {_fmt(item['end_ms'])}"
        return f"M - {start}"
    return f"{item['name']} - {_fmt(item['second'] * 1000)}"


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
    context_requested = Signal()  # right-click -> slide context menu

    def __init__(self) -> None:
        super().__init__(tr("player.no_folder"))
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
        if event.button() == Qt.RightButton:
            self.context_requested.emit()
            return
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

    frame_clicked = Signal(object)   # the clicked item (slide or mic dict)
    frame_context = Signal(object)   # right-clicked item
    THUMB_W = 140
    THUMB_H = 84
    GAP = 8

    def __init__(self) -> None:
        super().__init__()
        self._slides_dir: Path | None = None
        self._items: list = []
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

    def paintEvent(self, event) -> None:  # noqa: N802
        # Black backing so the strip looks the same (dark) even before a folder is
        # loaded — like the sort-out strip.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 22))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 40)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.THUMB_H + 40)

    def set_session(self, slides_dir: Path, items: list) -> None:
        """``items`` is the merged strip: slide dicts and mic-marker dicts (see
        Player._build_strip_items)."""
        self._slides_dir = slides_dir
        self._items = items
        self._current = 0
        self._cache.clear()
        self._rebuild()

    def set_current_slide(self, name: str) -> None:
        for i, it in enumerate(self._items):
            if it["kind"] == "slide" and it["name"] == name:
                if i != self._current:
                    self._current = i
                    self._rebuild()
                return

    def update_items(self, items: list) -> None:
        """Replace the items (e.g. when a mic length became known) but keep the
        centred element — same count and order, so the index still points to it."""
        self._items = items
        if self._current >= len(items):
            self._current = max(0, len(items) - 1)
        self._rebuild()

    def set_current_for_second(self, second: int) -> None:
        """Centre the latest strip element (slide or mic) whose time is at or
        before ``second`` — it stays centred until the next element is reached."""
        idx = latest_index_at_or_before(self._items, second)
        if idx is not None and idx != self._current:
            self._current = idx
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

    def _mic_pixmap(self) -> QPixmap:
        """White cell with a big black 'M' for a mic segment marker (cached)."""
        if "__mic__" in self._cache:
            return self._cache["__mic__"]
        pm = QPixmap(self.THUMB_W, self.THUMB_H)
        pm.fill(QColor(255, 255, 255))
        p = QPainter(pm)
        p.setPen(QColor(0, 0, 0))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(self.THUMB_H * 0.6))
        p.setFont(font)
        p.drawText(pm.rect(), Qt.AlignCenter, "M")
        p.end()
        self._cache["__mic__"] = pm
        return pm

    def _pixmap_for(self, item: dict) -> QPixmap | None:
        return self._mic_pixmap() if item["kind"] == "mic" else self._thumb(item["name"])

    def _caption_for(self, item: dict) -> str:
        return strip_caption(item)

    def _clear(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear()
        if not self._items:
            return
        for idx in visible_slots(len(self._items), self._current, self._slot_count()):
            if idx is None:
                self._row.addWidget(_Empty())
                continue
            item = self._items[idx]
            cell = _Cell(idx, self._pixmap_for(item), self._caption_for(item), idx == self._current)
            # Bind the item itself (not the index): a stale cell that is still
            # around during a rebuild can then never hit a shifted/shorter list.
            cell.clicked.connect(lambda _i, it=item: self.frame_clicked.emit(it))
            cell.context.connect(lambda _i, it=item: self.frame_context.emit(it))
            self._row.addWidget(cell)


class MicSegment:
    def __init__(self, start_sec: int, path: Path) -> None:
        self.start_ms = start_sec * 1000
        self.path = path
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
        self.setWindowTitle(f"{APP_NAME} – {tr('hub.player')}")

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
        self._path_lbl = QLabel(tr("player.no_folder_loaded"))
        self._path_lbl.setStyleSheet("color:#888;")
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        choose = QPushButton(tr("player.choose_folder_btn"))
        choose.clicked.connect(self._choose_folder)
        header = QHBoxLayout()
        header.addWidget(QLabel(tr("player.folder_label")))
        header.addWidget(self._path_lbl, stretch=1)
        header.addWidget(choose)

        # --- big slide + overlay ---
        self._slide = SlideLabel()
        self._overlay = ControlsOverlay()
        self._slide.attach_overlay(self._overlay)
        self._slide.setToolTip(tr("player.slide_tip"))
        self._slide.clicked.connect(self._on_image_click)
        self._slide.seek_back.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._slide.seek_forward.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        self._slide.hold_start.connect(self._hold_start)
        self._slide.hold_end.connect(self._hold_end)
        self._slide.context_requested.connect(self._show_slide_menu)
        self._hold_prev_rate = 1.0
        self._hold_prev_playing = False
        self._overlay.background_clicked.connect(self._on_image_click)
        self._overlay.back.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._overlay.forward.connect(lambda: self._seek_relative(SEEK_STEP_MS))
        self._overlay.play_pause.connect(self._toggle_play)
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._overlay.hide)

        self._fname = QLabel(tr("player.slide_none"))
        self._fname.setStyleSheet("color:#888;")

        self._filmstrip = FilmstripBar()
        self._filmstrip.frame_clicked.connect(self._on_frame_clicked)
        self._filmstrip.frame_context.connect(self._show_frame_menu)
        self._strip_left = QPushButton("‹")
        self._strip_left.setFixedWidth(28)
        self._strip_left.setAutoRepeat(True)
        self._strip_left.setAutoRepeatInterval(120)
        self._strip_left.clicked.connect(lambda: self._step_slide(-1))
        self._strip_right = QPushButton("›")
        self._strip_right.setFixedWidth(28)
        self._strip_right.setAutoRepeat(True)
        self._strip_right.setAutoRepeatInterval(120)
        self._strip_right.clicked.connect(lambda: self._step_slide(1))
        self._strip_row = QHBoxLayout()
        self._strip_row.setSpacing(4)
        self._strip_row.addWidget(self._strip_left)
        self._strip_row.addWidget(self._filmstrip, stretch=1)
        self._strip_row.addWidget(self._strip_right)

        # --- transport ---
        self._back_btn = QPushButton()
        self._back_btn.setIcon(skip_back_icon(26))      # circular "10" arrow, like the overlay
        self._back_btn.setToolTip(tr("player.back_tip"))
        self._back_btn.clicked.connect(lambda: self._seek_relative(-SEEK_STEP_MS))
        self._play_btn = QPushButton()
        self._play_btn.setIcon(play_icon(22))
        self._play_btn.clicked.connect(self._toggle_play)
        self._fwd_btn = QPushButton()
        self._fwd_btn.setIcon(skip_forward_icon(26))
        self._fwd_btn.setToolTip(tr("player.fwd_tip"))
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

        self._note_btn = QPushButton(tr("player.note"))
        self._note_btn.setStyleSheet(_TRANSPORT_BTN + "QPushButton{color:white;}")
        self._note_btn.setToolTip(tr("player.note_tip"))
        self._note_btn.clicked.connect(self._open_editor)

        controls = QHBoxLayout()
        controls.addWidget(self._back_btn)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._fwd_btn)
        controls.addWidget(self._slider, stretch=1)
        controls.addWidget(self._time)
        controls.addWidget(QLabel(tr("player.tempo")))
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
        vol_row.addWidget(QLabel(tr("player.system")))
        vol_row.addWidget(self._sys_vol)
        vol_row.addWidget(self._sys_vol_lbl)
        vol_row.addSpacing(16)
        vol_row.addWidget(QLabel(tr("player.mic")))
        vol_row.addWidget(self._mic_vol)
        vol_row.addWidget(self._mic_vol_lbl)

        # Mic-segment list with jump-to: a button whose menu lists each segment's
        # start time (mm:ss); choosing one seeks there and plays.
        self._seg_btn = QPushButton(tr("player.segments", n=0))
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
        layout.addLayout(self._strip_row)
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
        folder = QFileDialog.getExistingDirectory(self, tr("player.choose_folder_title"), start)
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
            # Mic length loads asynchronously -> refresh the strip caption (M - start
            # - end) once it is known.
            seg.player.durationChanged.connect(self._on_segment_duration)

        # Title stays "WebinarOD – Player"; the folder is shown in the Ordner line
        # (just the name, full path as tooltip, so a long path doesn't widen the
        # window).
        self._path_lbl.setText(session.name)
        self._path_lbl.setToolTip(str(session))
        self._rebuild_segment_menu()
        self._slider.setValue(0)
        self._time.setText("00:00 / 00:00")
        self._filmstrip.set_session(self._slides_dir, self._build_strip_items())
        self._update_play_icons(False)

        # Show the first slide immediately (lowest number, may be > 0).
        if self._frames:
            self.show_slide(self._frames[0].name)
        else:
            self._slide.setText(tr("player.no_slides_folder"))
            self._fname.setText("Folie: —")

    # ----- film strip model -----
    def _build_strip_items(self) -> list[dict]:
        """Merge slide frames and mic segments into one ordered strip. Mic markers
        are rendered as a white 'M' cell; they are NOT slides, so the slide before
        a mic segment keeps showing during playback (the timeline has no mic)."""
        return merge_strip_items(
            self._frames,
            [(seg.start_ms, seg.start_ms + seg.duration) for seg in self._segments],
        )

    def _on_segment_duration(self) -> None:
        # A mic segment's length became known -> update captions (M - start - end)
        # without disturbing which element is centred.
        self._filmstrip.update_items(self._build_strip_items())

    # ----- slides -----
    def show_slide(self, name: str) -> None:
        if self._slides_dir is None:
            return
        self._current_slide = name
        self._slide.set_slide_pixmap(QPixmap(str(self._slides_dir / name)))
        self._fname.setText(tr("player.slide", name=name))
        self._filmstrip.set_current_slide(name)

    def _update_slide(self, second: int) -> None:
        name = slide_for_second(self._timeline, second)
        if name and name != self._current_slide:
            self.show_slide(name)

    def _step_slide(self, delta: int) -> None:
        """Filmstrip arrows: jump to the previous/next slide (shown big + centred,
        audio follows) — mic markers are skipped."""
        if not self._frames:
            return
        idx = self._index_of.get(self._current_slide, 0)
        idx = max(0, min(len(self._frames) - 1, idx + delta))
        frame = self._frames[idx]
        self.show_slide(frame.name)
        self._seek(frame.second * 1000)

    def _on_frame_clicked(self, item: dict) -> None:
        if item["kind"] == "mic":
            # Same as picking the segment from the bottom-right dropdown: jump there
            # (the slide-before is shown via _update_slide) and start playing.
            self._jump_to_segment_ms(item["start_ms"])
            return
        self.show_slide(item["name"])
        self._seek(item["second"] * 1000)

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

    def _frame_by_name(self, name: str):
        for f in self._frames:
            if f.name == name:
                return f
        return None

    # ----- slide context menu (shared by big image and film strip) -----
    def _show_slide_menu(self) -> None:
        """Right-click on the big image: acts on the slide currently shown, and
        additionally offers 'Aufnahme verwerfen'."""
        self._show_slide_context_menu(self._current_slide, allow_discard=True)

    def _show_slide_context_menu(self, name: str | None, allow_discard: bool) -> None:
        if self._slides_dir is None or name is None:
            return
        menu = QMenu(self)
        act_edit = menu.addAction(tr("common.edit"))
        act_time = menu.addAction(tr("player.adjust_time"))
        menu.addSeparator()
        act_move = menu.addAction(tr("sort.menu_move"))
        act_del = menu.addAction(tr("sort.menu_delete"))
        act_discard = None
        # The time is shown in the label so it's clear the cut is at the PLAYHEAD,
        # not at this slide's timestamp. Snapshot it so the action cuts at exactly
        # the advertised time even if playback keeps running.
        t_ms = self._system.position()
        if allow_discard:
            menu.addSeparator()
            act_discard = menu.addAction(tr("player.discard_here", time=_fmt(t_ms)))
            act_discard.setEnabled(t_ms > 0)
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen == act_edit:
            self._edit_slide(name)
        elif chosen == act_time:
            self._adjust_slide_time(name)
        elif chosen == act_move:
            self._remove_slide(name, move=True)
        elif chosen == act_del:
            self._remove_slide(name, move=False)
        elif act_discard is not None and chosen == act_discard:
            self._discard_from_here(t_ms)

    def _discard_from_here(self, t_ms: int) -> None:
        """Trim the system track to ``t_ms`` (the playhead time shown in the menu)
        and permanently delete all mic segments that start at or after it
        (irreversible; confirmed first)."""
        if self._slides_dir is None:
            return
        session = self._slides_dir.parent
        sys_track = _find_track(session, "system")
        if sys_track is None or t_ms <= 0:
            return
        doomed = [s for s in self._segments if s.start_ms >= t_ms]
        if not ask_yes_no(
            self, tr("player.discard_title"),
            tr("player.discard_body", time=_fmt(t_ms), n=len(doomed)),
        ):
            return
        # Release every open handle before touching files (Windows locks them);
        # Qt frees them asynchronously, so the actual trim/delete runs in a worker
        # while a progress dialog keeps the window responsive.
        if self._is_playing():
            self._toggle_play()
        self._system.stop()
        self._system.setSource(QUrl())
        for s in self._segments:
            s.dispose()
        doomed_paths = [s.path for s in doomed]
        self._segments = []
        self._run_with_progress(
            tr("player.trimming"),
            _DiscardWorker(sys_track, t_ms / 1000.0, doomed_paths),
        )
        self.load_session(session)

    def _pump_until_writable(self, path: Path, tries: int = 80) -> bool:
        """GUI-thread variant of _wait_file_writable: pump the event loop so Qt can
        release its (asynchronously freed) handle on ``path``, then retry."""
        for _ in range(tries):
            QApplication.processEvents()
            try:
                with open(path, "r+b"):
                    return True
            except OSError:
                time.sleep(0.025)
        return False

    def _run_with_progress(self, label: str, worker: "QObject") -> None:
        """Run ``worker.run`` on a thread while a busy progress dialog is shown, so
        the GUI stays responsive (and Qt can release file handles) meanwhile."""
        dlg = QProgressDialog(label, None, 0, 0, self)  # 0..0 = busy/marquee
        dlg.setWindowTitle(tr("progress.wait_title"))
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.show()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.finished.connect(thread.quit)
        thread.start()
        loop.exec()
        thread.wait()
        dlg.close()

    def _remove_slide(self, name: str, move: bool) -> None:
        """Move (to _aussortiert) or delete the named slide, then refresh."""
        if self._slides_dir is None:
            return
        if move:
            if not move_slide(self._slides_dir, name):
                return
        else:
            if not delete_slide(self, self._slides_dir, name):
                return
        self._after_current_removed(name)

    def _adjust_slide_time(self, name: str) -> None:
        """Rename the named slide to a new second within the safe neighbour gap."""
        if self._slides_dir is None:
            return
        occupied = {f.second for f in self._frames}
        dur = self._system.duration() // 1000
        new_name = adjust_slide_time(
            self, self._slides_dir, name, occupied,
            duration_s=dur if dur > 0 else None, icon=app_icon(),
        )
        if not new_name:
            return
        was_current = name == self._current_slide
        if was_current:
            self._current_slide = new_name
        self._refresh_frames()
        if was_current:
            self.show_slide(new_name)

    # ----- film-strip context menu -----
    def _show_frame_menu(self, item: dict) -> None:
        if item["kind"] == "mic":
            menu = QMenu(self)
            act_move = menu.addAction(tr("sort.menu_move"))
            act_del = menu.addAction(tr("sort.menu_delete"))
            chosen = menu.exec(QCursor.pos())
            if chosen == act_move:
                self._remove_segment(item["start_ms"], move=True)
            elif chosen == act_del:
                self._remove_segment(item["start_ms"], move=False)
            return
        # A slide in the strip: same menu as the big image, minus 'Aufnahme verwerfen'.
        self._show_slide_context_menu(item["name"], allow_discard=False)

    def _remove_segment(self, start_ms: int, move: bool) -> None:
        """Move (to mikro/_aussortiert) or delete a mic segment file, then refresh
        the segment list and the film strip."""
        seg = next((s for s in self._segments if s.start_ms == start_ms), None)
        if seg is None:
            return
        path = seg.path
        if not move:
            if not ask_yes_no(self, tr("player.delete_seg_title"), tr("player.delete_body", name=path.name)):
                return
        # Release the file handle before touching the file (Windows locks it);
        # Qt frees it asynchronously, so pump events until the file is writable.
        seg.dispose()
        self._segments.remove(seg)
        self._pump_until_writable(path)
        if move:
            dest = path.parent / "_aussortiert"
            dest.mkdir(exist_ok=True)
            try:
                shutil.move(str(path), str(dest / path.name))
            except OSError:
                pass
        else:
            try:
                path.unlink()
            except OSError:
                pass
        self._rebuild_segment_menu()
        self._filmstrip.set_session(self._slides_dir, self._build_strip_items())
        if self._current_slide:
            self._filmstrip.set_current_slide(self._current_slide)

    def _edit_slide(self, name: str) -> None:
        """Edit the named image in place (overwrites the same file)."""
        frame = self._frame_by_name(name)
        if self._slides_dir is None or frame is None:
            return
        if self._is_playing():
            self._toggle_play()
        try:
            img = np.asarray(Image.open(self._slides_dir / name).convert("RGB"))
        except OSError:
            return
        self._editor = WorkAreaWindow(img, frame.second, self._slides_dir, save_as=name)
        self._editor.setWindowIcon(app_icon())
        self._editor.saved.connect(self._on_note_saved)
        self._editor.show()

    def _after_current_removed(self, name: str) -> None:
        """Refresh the strip after a slide file was removed/moved; if it was the
        one on screen, fall back to the slide for the current second."""
        was_current = name == self._current_slide
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
        self._filmstrip.set_session(self._slides_dir, self._build_strip_items())
        if self._current_slide:
            self._filmstrip.set_current_slide(self._current_slide)

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
        # Show the (new) total length as soon as it's known, before playback even
        # starts — both when opening a webinar and after trimming the track.
        if not self._slider.isSliderDown():
            self._time.setText(f"{_fmt(self._system.position())} / {_fmt(ms)}")

    def _on_position(self, ms: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.setValue(ms)
        self._time.setText(f"{_fmt(ms)} / {_fmt(self._system.duration())}")
        self._time.setToolTip(f"{ms // 1000} s")  # current time in seconds
        self._update_slide(ms // 1000)
        self._sync_segments(ms)
        self._filmstrip.set_current_for_second(ms // 1000)

    # ----- mic segment list / jump -----
    def _rebuild_segment_menu(self) -> None:
        self._seg_menu.clear()
        self._seg_btn.setText(tr("player.segments", n=len(self._segments)))
        self._seg_btn.setEnabled(bool(self._segments))
        for seg in sorted(self._segments, key=lambda s: s.start_ms):
            act = self._seg_menu.addAction(_fmt(seg.start_ms))
            act.triggered.connect(lambda _=False, s=seg: self._jump_to_segment(s))

    def _jump_to_segment(self, seg: "MicSegment") -> None:
        self._jump_to_segment_ms(seg.start_ms)

    def _jump_to_segment_ms(self, ms: int) -> None:
        self._seek(ms)
        self._update_slide(ms // 1000)                    # big image: slide that was on then
        self._filmstrip.set_current_for_second(ms // 1000)  # strip: centre the mic marker
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

    def closeEvent(self, event) -> None:  # noqa: N802
        # Stop all playback when the window closes; otherwise the audio keeps
        # running (the master player lives on) until the whole hub quits.
        #
        # Detach the position/duration signals FIRST: stopping a playing track
        # emits positionChanged, which would re-enter _on_position -> _sync_segments
        # across every mic segment while we are tearing them down — that cascade
        # froze the window ("not responding") when closing during playback.
        try:
            self._system.positionChanged.disconnect(self._on_position)
            self._system.durationChanged.disconnect(self._on_duration)
        except (RuntimeError, TypeError):
            pass
        self._system.stop()
        self._system.setSource(QUrl())
        for seg in self._segments:
            seg.dispose()
        super().closeEvent(event)


def open_player(session: Path | None = None) -> Player:
    """Create and show a player window (for the hub / in-process use)."""
    win = Player(session)
    win.setWindowIcon(app_icon())
    # Destroy on close (like the recorder) so the hub opens a fresh player next
    # time instead of re-showing a torn-down one — and the media objects are
    # released cleanly rather than lingering hidden.
    win.setAttribute(Qt.WA_DeleteOnClose, True)
    win.resize(960, 760)
    win.show()
    return win


def main() -> int:
    from core.i18n import init_language

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    init_language()
    session = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    open_player(session)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
