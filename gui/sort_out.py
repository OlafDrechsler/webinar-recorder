"""Slide-deduplication tool ("Folien aussortieren").

Post-processes a folder of slide screenshots: you mark the speaker area on a
reference image as an ignore region (rectangle or ellipse), and the tool walks
the images in ascending number order, removing those that are identical to the
previous kept image *outside* that region. The first of each identical run is
always kept.

Workflow (see also core/slide_dedupe.py for the comparison logic):
1. Pick the (pre-sorted) folder (chosen in the window header).
2. Draw one or more ignore regions on a reference image; step through images to
   find a representative one. Rectangle or ellipse; mode Ignorieren/Vergleichen.
3. Set the sensitivity and the action (move to ``_aussortiert`` vs. delete), then
   Start. A film strip animates each keep/discard decision so it is verifiable;
   a speed slider (slow↔fast) and Pause/Keep/Discard let you watch and intervene.
4. The chosen action is applied to the detected duplicates at the end of the run.

The browse list / film strip shows every slide scheme (auto ``NNNNN.png``, moved
``NNNNN_NN.png`` and annotated ``NNNNN_edit_/markiert_NN.png``) — the same as the
player — so all of them can be browsed and deduplicated. The last mask is
remembered (core.settings) and can also be saved/loaded as a file.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.discard import count_from_second, discard_from_second
from core.filmstrip import build_filmstrip
from core.i18n import tr
from core.naming import is_annotated
from core.settings import (
    get_data_dir,
    get_last_session,
    get_sortout_config,
    set_last_session,
    set_sortout_config,
)
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_yes_no
from gui.selection import next_selection
from gui.slide_ops import adjust_slide_time, delete_slide, fmt_seconds, move_slide, slide_second
from core.slide_dedupe import (
    COMPARE,
    ELLIPSE,
    IGNORE,
    RECT,
    Region,
    build_compare_mask,
    masked_frames_differ,
)


def load_frame(path: Path) -> np.ndarray:
    """Load an image as an RGB numpy array."""
    return np.asarray(Image.open(path).convert("RGB"))


def frame_to_qpixmap(frame: np.ndarray) -> QPixmap:
    h, w, _ = frame.shape
    contiguous = np.ascontiguousarray(frame)
    img = QImage(contiguous.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(img)


def slide_frames(folder: Path) -> list[Path]:
    """All slide frames in the folder — auto (``NNNNN.png``), moved
    (``NNNNN_NN.png``) and annotated (``NNNNN_edit_/markiert_NN.png``) — ordered by
    second then filename, i.e. the same recognition and order the player uses."""
    names = [p.name for p in folder.glob("*.png")]
    return [folder / f.name for f in build_filmstrip(names)]


def webinar_dir(folder: Path) -> Path:
    """The webinar folder for a slides folder: the parent when we resolved into a
    ``folien`` subfolder, else the folder itself. This is the value shared between
    tools (the player opens it directly; sort/crop resolve back into ``folien``)."""
    return folder.parent if folder.name == "folien" else folder


def webinar_name(folder: Path) -> str:
    """Meaningful folder name for the header: the parent (webinar) name when we
    resolved into a ``folien`` subfolder, otherwise the folder's own name — so it
    reads the same as the player instead of just 'folien'."""
    return webinar_dir(folder).name


class SortFilmstrip(QWidget):
    """Film strip that keeps EVERY frame visible. A dedup run walks a scan pointer
    across the frames and paints duplicates with a persistent red border (they are
    NOT removed) so the user can review and adjust them afterwards. Frame index ==
    strip position. Independent visual channels: red border = duplicate mark, blue
    fill = multi-selection, so a cell can carry both at once.
    """

    THUMB_W = 116
    THUMB_H = 70
    GAP = 8
    CAP_H = 16

    frame_clicked = Signal(int, object)  # left click: (index, keyboard modifiers)
    frame_context = Signal(int)          # right click: index into the frames list
    centered = Signal(int)               # the centred frame index changed (view moved)

    def __init__(self) -> None:
        super().__init__()
        self._frames: list[Path] = []
        self._center = 0
        self._browse = False
        self._range: tuple[int, int] | None = None   # yellow action-range band
        self._selected: set[int] = set()             # multi-select (blue fill)
        self._marked: set[int] = set()               # duplicates (red border)
        self._scan: tuple[int, int] | None = None    # (baseline, candidate) during a run
        self._cache: dict[str, QPixmap] = {}
        self.setFixedHeight(self.THUMB_H + self.CAP_H + 12)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_session(self, frames: list[Path]) -> None:
        self._frames = list(frames)
        self._cache.clear()
        self._center = 0
        self._marked = set()
        self._scan = None
        self.update()

    def count(self) -> int:
        return len(self._frames)

    def set_browse_mode(self, on: bool) -> None:
        self._browse = on
        self.update()

    def set_range(self, rng: tuple[int, int] | None) -> None:
        self._range = rng
        self.update()

    def set_selection(self, indices) -> None:
        self._selected = set(indices)
        self.update()

    def set_marked(self, indices) -> None:
        """The duplicates (red border), kept in view until the action is run."""
        self._marked = set(indices)
        self.update()

    def set_scan(self, baseline: int, candidate: int) -> None:
        """Highlight the current comparison (baseline + examined candidate) and
        follow the candidate while the run animates."""
        self._scan = (baseline, candidate)
        self.update()

    def clear_scan(self) -> None:
        self._scan = None
        self.update()

    def _effective_center(self) -> int:
        return self._scan[1] if self._scan is not None else self._center

    def scroll(self, delta: int) -> None:
        if self._frames:
            self.center_on(self._effective_center() + delta)

    def center_on(self, frame_index: int) -> None:
        if not self._frames:
            return
        frame_index = max(0, min(len(self._frames) - 1, frame_index))
        if frame_index != self._center:
            self._center = frame_index
            self.centered.emit(frame_index)
        self.update()

    # ----- click -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._frames:
            return
        step = self.THUMB_W + self.GAP
        pos = self._effective_center() + round((event.position().x() - self.width() / 2) / step)
        if 0 <= pos < len(self._frames):
            if event.button() == Qt.RightButton:
                self.frame_context.emit(pos)
            else:
                self.frame_clicked.emit(pos, event.modifiers())

    # ----- rendering -----
    def _thumb(self, idx: int) -> QPixmap | None:
        name = self._frames[idx].name
        if name in self._cache:
            return self._cache[name]
        pix = QPixmap(str(self._frames[idx]))
        if pix.isNull():
            return None
        scaled = pix.scaled(self.THUMB_W, self.THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._cache[name] = scaled
        return scaled

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 22))
        if not self._frames:
            return
        center = self._effective_center()
        step = self.THUMB_W + self.GAP
        cx = self.width() / 2
        n_side = int((self.width() / 2) // step) + 1
        for idx in range(max(0, center - n_side), min(len(self._frames), center + n_side + 1)):
            if self._range is not None and self._range[0] <= idx <= self._range[1]:
                band_x = int(cx + (idx - center) * step - (self.THUMB_W + self.GAP) / 2)
                p.fillRect(QRect(band_x, 0, self.THUMB_W + self.GAP, self.height()),
                           QColor(150, 130, 30))
            self._draw_cell(p, cx + (idx - center) * step, idx)

    def _draw_cell(self, p: QPainter, center_x: float, idx: int) -> None:
        x = int(center_x - self.THUMB_W / 2)
        y = 6
        rect = QRect(x, y, self.THUMB_W, self.THUMB_H)
        p.fillRect(rect, QColor(10, 10, 10))
        thumb = self._thumb(idx)
        if thumb is not None:
            p.drawPixmap(x + (self.THUMB_W - thumb.width()) // 2,
                         y + (self.THUMB_H - thumb.height()) // 2, thumb)
        if idx in self._selected:  # multi-select tint (independent of the border)
            p.fillRect(rect, QColor(45, 166, 255, 90))
        # Border encodes state; priority: scan candidate > duplicate (red) > scan
        # baseline > shown (browse) > plain.
        if self._scan is not None and idx == self._scan[1]:
            col, w = QColor(240, 240, 240), 3          # examining now
        elif idx in self._marked:
            col, w = QColor(230, 40, 40), 3            # duplicate
        elif self._scan is not None and idx == self._scan[0]:
            col, w = QColor(60, 200, 120), 2           # current baseline
        elif self._scan is None and idx == self._center:
            col, w = QColor(45, 166, 255), 2           # currently shown big
        else:
            col, w = QColor(70, 70, 70), 1
        p.setPen(QPen(col, w))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        p.setPen(QColor(170, 170, 170))
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        p.drawText(QRect(x, y + self.THUMB_H, self.THUMB_W, self.CAP_H),
                   Qt.AlignHCenter | Qt.AlignTop, self._frames[idx].name)


class MaskCanvas(QWidget):
    """Shows a reference image and lets the user draw rectangle/ellipse regions."""

    context_requested = Signal()  # right-click -> show the move/delete menu

    def __init__(self) -> None:
        super().__init__()
        self._base: QPixmap | None = None
        self._regions: list[dict] = []   # {shape,left,top,width,height} in image px
        self._tool = RECT
        self._origin: QPoint | None = None
        self._drag = QRect()
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ----- state -----
    def set_base(self, pixmap: QPixmap) -> None:
        self._base = pixmap
        self.update()

    def set_tool(self, tool: str) -> None:
        self._tool = tool

    def set_regions(self, regions: list[dict]) -> None:
        self._regions = list(regions)
        self.update()

    def regions(self) -> list[dict]:
        return list(self._regions)

    def clear_regions(self) -> None:
        self._regions = []
        self.update()

    def undo(self) -> None:
        if self._regions:
            self._regions.pop()
            self.update()

    # ----- coordinate mapping (widget <-> full-res image) -----
    def _display_rect(self) -> QRect:
        if self._base is None or self._base.width() == 0:
            return self.rect()
        bw, bh = self._base.width(), self._base.height()
        scale = min(self.width() / bw, self.height() / bh)
        dw, dh = int(bw * scale), int(bh * scale)
        return QRect((self.width() - dw) // 2, (self.height() - dh) // 2, dw, dh)

    def _scale(self) -> float:
        if self._base is None or self._base.width() == 0:
            return 1.0
        return min(self.width() / self._base.width(), self.height() / self._base.height())

    def _to_image(self, p: QPoint) -> QPoint:
        rect, scale = self._display_rect(), self._scale()
        ix = (p.x() - rect.left()) / scale
        iy = (p.y() - rect.top()) / scale
        bw = self._base.width() if self._base else 1
        bh = self._base.height() if self._base else 1
        return QPoint(int(max(0, min(bw - 1, ix))), int(max(0, min(bh - 1, iy))))

    def _img_rect_to_widget(self, l: int, t: int, w: int, h: int) -> QRect:
        rect, scale = self._display_rect(), self._scale()
        return QRect(
            int(rect.left() + l * scale), int(rect.top() + t * scale),
            int(w * scale), int(h * scale),
        )

    # ----- painting -----
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        if self._base is not None:
            painter.drawPixmap(self._display_rect(), self._base)
        for reg in self._regions:
            self._draw_region(painter, reg["shape"],
                              self._img_rect_to_widget(reg["left"], reg["top"],
                                                       reg["width"], reg["height"]))
        if self._origin is not None and not self._drag.isNull():
            wr = self._img_rect_to_widget(self._drag.left(), self._drag.top(),
                                          self._drag.width(), self._drag.height())
            self._draw_region(painter, self._tool, wr)

    def _draw_region(self, painter: QPainter, shape: str, wr: QRect) -> None:
        painter.setPen(QPen(QColor(255, 60, 60), 2))
        painter.setBrush(QColor(255, 60, 60, 60))
        if shape == ELLIPSE:
            painter.drawEllipse(wr)
        else:
            painter.drawRect(wr)
        painter.setBrush(Qt.NoBrush)

    # ----- mouse -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.context_requested.emit()
            return
        if self._base is None:
            return
        self._origin = self._to_image(event.position().toPoint())
        self._drag = QRect(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._drag = QRect(self._origin, self._to_image(event.position().toPoint())).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None and self._drag.width() > 3 and self._drag.height() > 3:
            self._regions.append({
                "shape": self._tool,
                "left": self._drag.left(), "top": self._drag.top(),
                "width": self._drag.width(), "height": self._drag.height(),
            })
        self._origin = None
        self._drag = QRect()
        self.update()


class SortOutWindow(QWidget):
    def __init__(self, folder: Path | None = None) -> None:
        super().__init__()
        self._folder: Path | None = None
        self._paths: list[Path] = []
        self._ref_index = 0
        self._mask_mode = IGNORE
        self._action = "move"  # "move" or "delete"
        self.setWindowTitle(f"{APP_NAME} – {tr('hub.sort')}")
        self.setWindowIcon(app_icon())

        # Folder picker in the header (like the player) — no separate dialog window.
        self._path_lbl = QLabel(tr("player.no_folder_loaded"))
        self._path_lbl.setStyleSheet("color:#888;")
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._folder_btn = QPushButton(tr("player.choose_folder_btn"))
        self._folder_btn.clicked.connect(self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("player.folder_label")))
        folder_row.addWidget(self._path_lbl, stretch=1)
        folder_row.addWidget(self._folder_btn)

        self._canvas = MaskCanvas()
        self._canvas.context_requested.connect(self._show_image_menu)
        self._ref_label = QLabel()

        # Reference-image stepping.
        prev_btn = QPushButton(tr("sort.prev"))
        prev_btn.clicked.connect(lambda: self._step_ref(-1))
        next_btn = QPushButton(tr("sort.next"))
        next_btn.clicked.connect(lambda: self._step_ref(1))
        ref_row = QHBoxLayout()
        ref_row.addWidget(prev_btn)
        ref_row.addWidget(self._ref_label, stretch=1)
        ref_row.addWidget(next_btn)

        # Drawing tools.
        rect_btn = QPushButton(tr("sort.rect"))
        rect_btn.clicked.connect(lambda: self._canvas.set_tool(RECT))
        ell_btn = QPushButton(tr("sort.ellipse"))
        ell_btn.clicked.connect(lambda: self._canvas.set_tool(ELLIPSE))
        undo_btn = QPushButton(tr("sort.remove_last"))
        undo_btn.clicked.connect(self._canvas.undo)
        clear_btn = QPushButton(tr("sort.clear_all"))
        clear_btn.clicked.connect(self._canvas.clear_regions)
        self._mode_btn = QPushButton()
        self._mode_btn.clicked.connect(self._toggle_mask_mode)
        tools = QHBoxLayout()
        for b in (rect_btn, ell_btn, undo_btn, clear_btn, self._mode_btn):
            tools.addWidget(b)

        # Sensitivity + mask file.
        self._thr = QSlider(Qt.Horizontal)
        self._thr.setRange(1, 50)          # 0.1% .. 5.0%
        self._thr.setValue(5)              # 0.5%
        self._thr.valueChanged.connect(self._update_thr_label)
        self._thr_label = QLabel()
        save_btn = QPushButton(tr("sort.mask_save"))
        save_btn.clicked.connect(self._save_mask_file)
        load_btn = QPushButton(tr("sort.mask_load"))
        load_btn.clicked.connect(self._load_mask_file)
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel(tr("sort.sensitivity")))
        thr_row.addWidget(self._thr, stretch=1)
        thr_row.addWidget(self._thr_label)
        thr_row.addWidget(save_btn)
        thr_row.addWidget(load_btn)

        # Animated film strip with paging arrows + run controls.
        self._filmstrip = SortFilmstrip()
        self._filmstrip.frame_clicked.connect(self._on_strip_click)
        self._filmstrip.frame_context.connect(self._slide_menu_at)
        strip_first = QPushButton("«")   # jump to the first slide
        strip_first.setFixedWidth(28)
        strip_first.clicked.connect(lambda: self._filmstrip.center_on(0))
        strip_left = QPushButton("‹")
        strip_left.setFixedWidth(28)
        strip_left.setAutoRepeat(True)
        strip_left.setAutoRepeatInterval(60)
        strip_left.clicked.connect(lambda: self._filmstrip.scroll(-1))
        strip_right = QPushButton("›")
        strip_right.setFixedWidth(28)
        strip_right.setAutoRepeat(True)
        strip_right.setAutoRepeatInterval(60)
        strip_right.clicked.connect(lambda: self._filmstrip.scroll(1))
        strip_last = QPushButton("»")     # jump to the last slide
        strip_last.setFixedWidth(28)
        strip_last.clicked.connect(lambda: self._filmstrip.center_on(self._filmstrip.count() - 1))
        strip_row = QHBoxLayout()
        strip_row.setSpacing(4)
        strip_row.addWidget(strip_first)
        strip_row.addWidget(strip_left)
        strip_row.addWidget(self._filmstrip, stretch=1)
        strip_row.addWidget(strip_right)
        strip_row.addWidget(strip_last)

        # Scroll bar to jump anywhere in the strip (for very long recordings).
        self._strip_scroll = QScrollBar(Qt.Horizontal)
        self._strip_scroll.valueChanged.connect(self._filmstrip.center_on)
        self._filmstrip.centered.connect(self._on_strip_centered)

        self._speed = QSlider(Qt.Horizontal)
        self._speed.setRange(0, 100)   # 0 = slow (2 s/step), 100 = fast (no delay)
        self._speed.setValue(0)
        self._pause_btn = QPushButton(tr("sort.pause"))
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setVisible(False)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel(tr("sort.speed_slow")))
        run_row.addWidget(self._speed, stretch=1)
        run_row.addWidget(QLabel(tr("sort.speed_fast")))
        run_row.addSpacing(12)
        run_row.addWidget(self._pause_btn)

        # Action toggle + Start (mark) + Execute (apply the red marks).
        self._action_btn = QPushButton()
        self._action_btn.clicked.connect(self._toggle_action)
        self._run_btn = QPushButton(tr("common.start"))
        self._run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._exec_btn = QPushButton()
        self._exec_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._exec_btn.clicked.connect(self._execute_marked)
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self._action_btn)
        action_row.addWidget(self._run_btn)
        action_row.addWidget(self._exec_btn)  # right-aligned, dimmed until marks exist

        self._status = QLabel()

        # Run state.
        self._running = False
        self._paused = False
        self._mask = None
        self._fraction_val = 0.005
        self._baseline_idx: int | None = None
        self._baseline_frame = None
        self._compare_idx = 0  # index of the last kept NON-annotated frame (compare ref)
        self._cand = 0         # next candidate index the scan will examine
        self._run_hi = 0       # last index of the scanned range
        self._after_range_name: str | None = None  # slide right after the 'bis hier' end
        self._marked: set[str] = set()  # names of duplicates (red), kept for review
        self._range_start: int | None = None  # action range (indices into _paths)
        self._range_end: int | None = None
        self._selection: set[int] = set()  # multi-selected frame indices
        self._anchor: int | None = None    # for shift-range selection
        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._do_phase)

        layout = QVBoxLayout(self)
        layout.addLayout(folder_row)
        layout.addLayout(ref_row)
        layout.addWidget(self._canvas, stretch=1)
        layout.addLayout(tools)
        layout.addLayout(thr_row)
        layout.addLayout(strip_row)
        layout.addWidget(self._strip_scroll)
        layout.addLayout(run_row)
        layout.addLayout(action_row)
        layout.addWidget(self._status)
        self.resize(960, 860)

        self._update_thr_label(self._thr.value())
        self._refresh_mode_labels()
        self._refresh_exec_btn()
        # Capture ←/→/Entf window-wide so a focused slider/scrollbar can't swallow
        # them (Qt would otherwise use the arrows for value change / focus stepping).
        QApplication.instance().installEventFilter(self)
        if folder is not None:
            self._load_folder(folder)

    # ----- folder selection (in-window) -----
    def _choose_folder(self) -> None:
        start = str(self._folder.parent if self._folder else get_data_dir())
        chosen = QFileDialog.getExistingDirectory(self, tr("sort.choose_folder"), start)
        if chosen:
            self._load_folder(Path(chosen))

    def _load_folder(self, folder: Path) -> None:
        folder = Path(folder)
        # Accept a parent webinar folder (any name): if it has no slide PNGs
        # directly but a "folien" subfolder does, use that.
        if not slide_frames(folder) and (folder / "folien").is_dir() and slide_frames(folder / "folien"):
            folder = folder / "folien"
        self._folder = folder
        set_last_session(webinar_dir(self._folder))  # share the folder with the other tools
        self._paths = slide_frames(self._folder)
        self._ref_index = 0
        self._path_lbl.setText(webinar_name(self._folder))
        self._path_lbl.setToolTip(str(self._folder))
        self._apply_saved_config()
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)  # first image centred, rest to the right
        self._filmstrip.set_browse_mode(True)     # highlight the shown slide while browsing
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._marked = set()
        self._filmstrip.set_marked(set())
        self._refresh_exec_btn()
        self._sync_scroll()
        self._status.setText(tr("sort.no_slides") if not self._paths else "")

    # ----- reference image + multi-select -----
    def _on_strip_click(self, frame_index: int, modifiers=None) -> None:
        """Show the clicked film-strip image big; Ctrl/Shift build a multi-select."""
        if not (0 <= frame_index < len(self._paths)):
            return
        self._ref_index = frame_index
        self._refresh_ref()
        if not self._running:
            self._update_selection(frame_index, modifiers)
            self._filmstrip.center_on(self._ref_index)

    def _update_selection(self, index: int, modifiers) -> None:
        ctrl = bool(modifiers) and bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers) and bool(modifiers & Qt.ShiftModifier)
        if not ctrl and not shift:
            self._selection = set()   # plain click = browse, no lingering selection
            self._anchor = index
        else:
            self._selection, self._anchor = next_selection(
                list(range(len(self._paths))), self._selection, self._anchor, index, ctrl, shift)
        self._filmstrip.set_selection(self._selection)

    def _clear_selection(self) -> None:
        self._selection = set()
        self._anchor = None
        self._filmstrip.set_selection(set())

    def _show_image_menu(self) -> None:
        """Right-click on the big image: act on THE SHOWN slide."""
        self._slide_menu_at(self._ref_index)

    def _slide_menu_at(self, index: int) -> None:
        """Context menu for a slide: bulk actions when several are selected,
        otherwise the single-slide menu (adjust/move/delete/range)."""
        if self._running or not (0 <= index < len(self._paths)):
            return
        if len(self._selection) > 1 and index in self._selection:
            self._bulk_menu()
            return
        menu = QMenu(self)
        act_mark = menu.addAction(tr("sort.toggle_mark"))  # flip Baseline/Doublette
        act_time = menu.addAction(tr("player.adjust_time"))
        menu.addSeparator()
        act_move = menu.addAction(tr("sort.menu_move"))
        act_del = menu.addAction(tr("sort.menu_delete"))
        menu.addSeparator()
        act_from = menu.addAction(tr("range.from_here"))
        act_to = menu.addAction(tr("range.to_here"))
        act_clear = menu.addAction(tr("range.clear"))
        act_clear.setEnabled(self._range_start is not None or self._range_end is not None)
        menu.addSeparator()
        t = slide_second(self._paths[index].name)
        act_discard = menu.addAction(tr("discard.from_here", time=fmt_seconds(t or 0)))
        act_discard.setEnabled(t is not None)
        chosen = menu.exec(QCursor.pos())
        if chosen == act_mark:
            self._toggle_mark(index)
        elif chosen == act_time:
            self._adjust_slide_time_at(index)
        elif chosen == act_move:
            self._remove_slide_at(index, move=True)
        elif chosen == act_del:
            self._remove_slide_at(index, move=False)
        elif chosen == act_from:
            self._range_start = index
            self._apply_range_highlight()
        elif chosen == act_to:
            self._range_end = index
            self._apply_range_highlight()
        elif chosen == act_clear:
            self._clear_range()
        elif chosen == act_discard:
            self._discard_from(index)

    def _discard_from(self, index: int) -> None:
        """Discard the tail: trim the system track to this slide's second and delete
        all slides and mic segments at or after it (irreversible; confirmed)."""
        if self._running or not (0 <= index < len(self._paths)):
            return
        t = slide_second(self._paths[index].name)
        if t is None:
            return
        session = webinar_dir(self._folder)
        n_slides, n_mics = count_from_second(self._folder, session / "mikro", t)
        if not ask_yes_no(self, tr("discard.confirm_title"),
                          tr("discard.confirm_body", time=fmt_seconds(t), slides=n_slides, mics=n_mics)):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            discard_from_second(session, self._folder, t)
        finally:
            QApplication.restoreOverrideCursor()
        self._paths = slide_frames(self._folder)
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._marked = set()
        self._filmstrip.set_marked(set())
        self._refresh_exec_btn()
        self._sync_scroll()
        self._status.setText(tr("discard.done", time=fmt_seconds(t), slides=n_slides, mics=n_mics))

    def _bulk_menu(self) -> None:
        n = len(self._selection)
        menu = QMenu(self)
        act_mark = menu.addAction(tr("sort.toggle_mark_n", n=n))
        menu.addSeparator()
        act_move = menu.addAction(tr("multi.move", n=n))
        act_del = menu.addAction(tr("multi.delete", n=n))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_mark:
            self._toggle_mark_selected()
        elif chosen == act_move:
            self._remove_selected(move=True)
        elif chosen == act_del:
            self._remove_selected(move=False)

    def _remove_selected(self, move: bool) -> None:
        names = [self._paths[i].name for i in sorted(self._selection)
                 if 0 <= i < len(self._paths)]
        if not names:
            return
        if not move:
            if not ask_yes_no(self, tr("multi.delete_title"), tr("multi.delete_body", n=len(names))):
                return
        shown = self._paths[self._ref_index].name if 0 <= self._ref_index < len(self._paths) else None
        # slide right after the last selected one -> framed & shown afterwards
        last = max(self._selection)
        after = self._paths[last + 1].name if last + 1 < len(self._paths) else None
        for name in names:
            if move:
                move_slide(self._folder, name)
            else:
                try:
                    (self._folder / name).unlink()
                except OSError:
                    pass
        self._clear_selection()
        self._reload_showing(after or (shown if shown not in names else ""))

    def _effective_range(self) -> tuple[int, int]:
        """(lo, hi) the action applies to; full list when no bound is set."""
        lo = self._range_start if self._range_start is not None else 0
        hi = self._range_end if self._range_end is not None else len(self._paths) - 1
        return (min(lo, hi), max(lo, hi))

    def _apply_range_highlight(self) -> None:
        if self._range_start is None and self._range_end is None:
            self._filmstrip.set_range(None)
        else:
            self._filmstrip.set_range(self._effective_range())

    def _clear_range(self) -> None:
        self._range_start = None
        self._range_end = None
        self._filmstrip.set_range(None)

    def _reload_showing(self, name: str) -> None:
        """Reload the auto-frame list and keep ``name`` shown/centred if it still
        exists, otherwise clamp the reference index into the shortened list."""
        self._paths = slide_frames(self._folder)
        idx = next((i for i, p in enumerate(self._paths) if p.name == name), None)
        self._ref_index = idx if idx is not None else min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.center_on(self._ref_index)
        self._push_marks()  # marks are by name -> survive the reload
        self._refresh_exec_btn()
        self._sync_scroll()

    def _remove_slide_at(self, index: int, move: bool) -> None:
        name = self._paths[index].name
        shown = self._paths[self._ref_index].name  # keep this one shown if it survives
        if move:
            if not move_slide(self._folder, name):
                return
        else:
            if not delete_slide(self, self._folder, name):
                return
        self._reload_showing(shown)

    def _adjust_slide_time_at(self, index: int) -> None:
        name = self._paths[index].name
        occupied = {slide_second(p.name) for p in self._folder.glob("*.png")}
        occupied.discard(None)
        new_name = adjust_slide_time(self, self._folder, name, occupied, icon=app_icon())
        if new_name:
            self._reload_showing(new_name)

    def _on_strip_centered(self, value: int) -> None:
        self._strip_scroll.blockSignals(True)
        self._strip_scroll.setValue(value)
        self._strip_scroll.blockSignals(False)

    def _sync_scroll(self) -> None:
        self._strip_scroll.blockSignals(True)
        self._strip_scroll.setRange(0, max(0, len(self._paths) - 1))
        self._strip_scroll.setValue(min(self._ref_index, max(0, len(self._paths) - 1)))
        self._strip_scroll.blockSignals(False)

    def _step_ref(self, delta: int) -> None:
        if not self._paths:
            return
        self._ref_index = (self._ref_index + delta) % len(self._paths)
        self._refresh_ref()
        self._filmstrip.center_on(self._ref_index)  # strip follows the big image

    def _key_navigate(self, delta: int, shift: bool) -> None:
        """←/→ move one slide (clamped). With Shift the move extends the blue
        multi-selection from the anchor (start & control the marked range)."""
        if not self._paths:
            return
        old = self._ref_index
        new = max(0, min(len(self._paths) - 1, old + delta))
        self._ref_index = new
        if shift:
            if self._anchor is None:
                self._anchor = old  # anchor where the range starts
            self._selection, self._anchor = next_selection(
                list(range(len(self._paths))), self._selection, self._anchor, new, False, True)
            self._filmstrip.set_selection(self._selection)
        else:
            self._selection = set()
            self._anchor = new
            self._filmstrip.set_selection(set())
        self._refresh_ref()
        self._filmstrip.center_on(new)

    def _handle_key(self, event) -> bool:
        """Shared ←/→/Entf handling for keyPressEvent and the app event filter.
        Returns True when the key was consumed."""
        key = event.key()
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        if key in (Qt.Key_Left, Qt.Key_Right):
            if not self._running:
                self._key_navigate(-1 if key == Qt.Key_Left else 1, shift)
            return True
        if key == Qt.Key_Delete:
            if self._running:
                return True
            move = not shift  # Entf = verschieben, Shift+Entf = endgültig löschen
            if self._selection:
                self._remove_selected(move=move)
            elif self._paths:
                self._remove_slide_at(self._ref_index, move=move)
            return True
        return False

    def keyPressEvent(self, event) -> None:
        if not self._handle_key(event):
            super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """Intercept ←/→/Entf while this window is active so focused sliders or the
        scrollbar can't consume them — unless a text field has focus."""
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QAbstractSpinBox)) and self._handle_key(event):
                return True
        return super().eventFilter(obj, event)

    def _refresh_ref(self) -> None:
        if not self._paths:
            self._ref_label.setText("—")
            return
        path = self._paths[self._ref_index]
        self._canvas.set_base(frame_to_qpixmap(load_frame(path)))
        self._ref_label.setText(
            tr("sort.reference", i=self._ref_index + 1, n=len(self._paths), name=path.name)
        )

    # ----- toggles / labels -----
    def _toggle_mask_mode(self) -> None:
        self._mask_mode = COMPARE if self._mask_mode == IGNORE else IGNORE
        self._refresh_mode_labels()

    def _toggle_action(self) -> None:
        self._action = "delete" if self._action == "move" else "move"
        self._refresh_mode_labels()

    def _refresh_mode_labels(self) -> None:
        self._mode_btn.setText(
            tr("sort.mode_ignore") if self._mask_mode == IGNORE else tr("sort.mode_compare")
        )
        if self._action == "move":
            self._action_btn.setText(tr("sort.action_move"))
            self._action_btn.setStyleSheet("")
        else:
            self._action_btn.setText(tr("sort.action_delete").upper())  # red -> shout
            self._action_btn.setStyleSheet("color: white; background: #b00;")

    def _update_thr_label(self, value: int) -> None:
        self._thr_label.setText(f"{value / 10:.1f} %")

    def _fraction(self) -> float:
        return (self._thr.value() / 10.0) / 100.0

    # ----- mask config -----
    def _regions(self) -> list[Region]:
        return [Region(r["shape"], r["left"], r["top"], r["width"], r["height"])
                for r in self._canvas.regions()]

    def _current_mask(self) -> np.ndarray | None:
        if self._canvas._base is None:
            return None
        w = self._canvas._base.width()
        h = self._canvas._base.height()
        return build_compare_mask(w, h, self._regions(), self._mask_mode)

    def _config_dict(self) -> dict:
        base = self._canvas._base
        return {
            "mode": self._mask_mode,
            "action": self._action,
            "threshold_slider": self._thr.value(),
            "ref_width": base.width() if base else 0,
            "ref_height": base.height() if base else 0,
            "regions": self._canvas.regions(),
        }

    def _apply_config(self, cfg: dict) -> None:
        self._mask_mode = cfg.get("mode", IGNORE)
        self._action = cfg.get("action", "move")
        self._thr.setValue(int(cfg.get("threshold_slider", 5)))
        regions = cfg.get("regions", [])
        # Scale saved regions to the current image size if it differs.
        ref_w = cfg.get("ref_width", 0) or 0
        ref_h = cfg.get("ref_height", 0) or 0
        if self._paths and ref_w and ref_h:
            frame = load_frame(self._paths[self._ref_index])
            cur_h, cur_w = frame.shape[:2]
            if (cur_w, cur_h) != (ref_w, ref_h):
                sx, sy = cur_w / ref_w, cur_h / ref_h
                regions = [{
                    "shape": r["shape"],
                    "left": round(r["left"] * sx), "top": round(r["top"] * sy),
                    "width": round(r["width"] * sx), "height": round(r["height"] * sy),
                } for r in regions]
        self._canvas.set_regions(regions)
        self._refresh_mode_labels()

    def _apply_saved_config(self) -> None:
        cfg = get_sortout_config()
        if cfg:
            self._apply_config(cfg)

    def _save_mask_file(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, tr("sort.mask_save_title"), "", "JSON (*.json)")
        if name:
            Path(name).write_text(json.dumps(self._config_dict(), indent=2), encoding="utf-8")

    def _load_mask_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, tr("sort.mask_load_title"), "", "JSON (*.json)")
        if name:
            try:
                self._apply_config(json.loads(Path(name).read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("sort.load_failed"), str(exc))

    # ----- animated run -----
    def _delay_ms(self) -> int:
        # slow (0) = 2000 ms/step, fast (100) = 0 ms (as fast as comparing allows).
        return round(2000 * (100 - self._speed.value()) / 100)

    def _baseline_frame_for(self, idx: int):
        if self._baseline_idx != idx or self._baseline_frame is None:
            self._baseline_idx = idx
            self._baseline_frame = load_frame(self._paths[idx])
        return self._baseline_frame

    def _on_run_clicked(self) -> None:
        """The one button is Start outside a run and ABBRECHEN during one."""
        if self._running:
            self._cancel_run()
        else:
            self._run()

    def _cancel_run(self) -> None:
        """Abort the marking run: nothing was applied, so just drop the marks."""
        self._running = False
        self._paused = False
        self._step_timer.stop()
        self._marked = set()
        self._filmstrip.clear_scan()
        self._filmstrip.set_marked(set())
        self._filmstrip.set_browse_mode(True)
        self._set_run_ui(False)
        self._clear_range()
        self._clear_selection()
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.center_on(self._ref_index)
        self._refresh_exec_btn()
        self._status.setText(tr("sort.cancelled"))

    def _run(self) -> None:
        """Start (Start button): walk the range and MARK duplicates red. Nothing is
        moved/deleted here — the user reviews the marks and then runs 'Ausführen'."""
        if self._running:
            return
        mask = self._current_mask()
        if mask is None or not self._paths:
            QMessageBox.information(self, tr("sort.nothing_title"), tr("sort.nothing_body"))
            return
        lo, hi = self._effective_range()
        if not (lo <= self._ref_index <= hi):  # mask drawn on a slide not scanned?
            if not ask_yes_no(self, tr("range.outside_title"), tr("range.outside_body")):
                return
        # remember the slide right after the 'bis hier' end (only when a range was set),
        # so after executing the action we can jump to it.
        explicit_end = self._range_end if self._range_end is not None else len(self._paths) - 1
        self._after_range_name = (
            self._paths[explicit_end + 1].name if explicit_end + 1 < len(self._paths) else None)
        set_sortout_config(self._config_dict())
        self._mask = mask
        self._fraction_val = self._fraction()
        self._baseline_idx = None
        self._baseline_frame = None
        self._compare_idx = lo
        self._cand = lo + 1
        self._run_hi = hi
        self._marked = set()
        self._clear_selection()
        self._clear_range()
        self._filmstrip.set_session(self._paths)  # resets marks/scan
        self._filmstrip.set_browse_mode(False)
        self._running = True
        self._paused = False
        self._set_run_ui(True)
        self._ref_index = lo
        self._refresh_ref()
        self._filmstrip.set_scan(self._compare_idx, min(self._cand, hi))
        self._schedule()

    def _schedule(self) -> None:
        if self._running and not self._paused:
            self._step_timer.start(self._delay_ms())

    def _do_phase(self) -> None:
        if not self._running or self._paused:
            return
        if self._cand > self._run_hi:
            self._end_run()
            return
        cand = self._cand
        if is_annotated(self._paths[cand].name):
            pass  # annotated frames are never marked and never become the baseline
        else:
            base = self._baseline_frame_for(self._compare_idx)
            img = load_frame(self._paths[cand])
            if masked_frames_differ(base, img, self._mask, fraction_threshold=self._fraction_val):
                self._compare_idx = cand      # a different slide -> new baseline
            else:
                self._marked.add(self._paths[cand].name)  # duplicate -> red (kept in view)
        self._push_marks()
        self._filmstrip.set_scan(self._compare_idx, cand)
        self._ref_index = cand
        self._refresh_ref()                    # show the slide being examined
        self._cand += 1
        self._schedule()

    def _push_marks(self) -> None:
        """Convert the marked NAMES to current indices for the film strip (names
        survive reloads that shift indices)."""
        self._filmstrip.set_marked(
            {i for i, p in enumerate(self._paths) if p.name in self._marked})

    def _end_run(self) -> None:
        """Marking finished — keep the red marks for review; enable 'Ausführen'."""
        self._running = False
        self._paused = False
        self._step_timer.stop()
        self._filmstrip.clear_scan()
        self._filmstrip.set_browse_mode(True)
        self._push_marks()
        self._set_run_ui(False)
        self._refresh_exec_btn()
        n = len(self._marked)
        self._status.setText(tr("sort.marked", n=n) if n else tr("sort.none_found"))

    def _toggle_pause(self) -> None:
        if not self._running:
            return
        if self._paused:
            self._paused = False
            self._pause_btn.setText(tr("sort.pause"))
            self._schedule()
        else:
            self._paused = True
            self._step_timer.stop()
            self._pause_btn.setText(tr("common.next"))

    # ----- duplicate marks (review) -----
    def _toggle_mark(self, index: int) -> None:
        if not (0 <= index < len(self._paths)):
            return
        name = self._paths[index].name
        self._marked.discard(name) if name in self._marked else self._marked.add(name)
        self._push_marks()
        self._refresh_exec_btn()

    def _toggle_mark_selected(self) -> None:
        for i in self._selection:
            if 0 <= i < len(self._paths):
                name = self._paths[i].name
                self._marked.discard(name) if name in self._marked else self._marked.add(name)
        self._push_marks()
        self._refresh_exec_btn()

    def _refresh_exec_btn(self) -> None:
        n = len(self._marked)
        self._exec_btn.setText(tr("sort.execute", n=n))
        self._exec_btn.setEnabled(not self._running and n > 0)

    def _execute_marked(self) -> None:
        """Apply the current action (move/delete) to all red-marked duplicates."""
        if self._running:
            return
        names = [p.name for p in self._paths if p.name in self._marked]
        if not names:
            return
        if self._action == "delete":
            if not ask_yes_no(self, tr("multi.delete_title"), tr("multi.delete_body", n=len(names))):
                return
        kept = self._paths[self._ref_index].name if 0 <= self._ref_index < len(self._paths) else None
        if self._action == "move":
            dest = self._folder / "_aussortiert"
            dest.mkdir(exist_ok=True)
            for name in names:
                try:
                    shutil.move(str(self._folder / name), str(dest / name))
                except OSError:
                    pass
        else:
            for name in names:
                try:
                    (self._folder / name).unlink()
                except OSError:
                    pass
        self._marked = set()
        self._clear_selection()
        self._paths = slide_frames(self._folder)
        # prefer the slide right after the 'bis hier' end; fall back to the last shown slide
        target = self._after_range_name or kept
        idx = next((i for i, p in enumerate(self._paths) if p.name == target), None)
        if idx is None and target != kept:
            idx = next((i for i, p in enumerate(self._paths) if p.name == kept), None)
        self._after_range_name = None
        self._ref_index = idx if idx is not None else min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._refresh_exec_btn()
        self._sync_scroll()
        done = tr("sort.moved" if self._action == "move" else "sort.deleted", n=len(names))
        self._status.setText(tr("sort.remaining", done=done, n=len(self._paths)))

    def _set_run_ui(self, running: bool) -> None:
        # The Start button stays enabled: during the marking run it becomes ABBRECHEN.
        self._run_btn.setText(tr("sort.cancel_run") if running else tr("common.start"))
        self._action_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self._exec_btn.setEnabled(not running and bool(self._marked))
        self._pause_btn.setVisible(running)
        if running:
            self._pause_btn.setText(tr("sort.pause"))


def open_sorter(folder: Path | None = None) -> SortOutWindow:
    """Open the sort-out window; defaults to the folder shared with the other
    tools (last recorded/opened) when none is given."""
    win = SortOutWindow(folder or get_last_session())
    win.setWindowIcon(app_icon())
    win.show()
    return win


def main() -> int:
    from core.i18n import init_language

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    init_language()
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    open_sorter(folder)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
