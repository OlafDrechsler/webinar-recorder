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

``*_markiert_*`` files (your annotations) are never touched. The last mask is
remembered (core.settings) and can also be saved/loaded as a file.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.i18n import tr
from core.settings import get_data_dir, get_sortout_config, set_sortout_config
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_yes_no
from core.slide_dedupe import (
    COMPARE,
    ELLIPSE,
    IGNORE,
    RECT,
    Region,
    build_compare_mask,
    masked_frames_differ,
    numeric_key,
)

_AUTO_FRAME = re.compile(r"^\d+\.png$", re.IGNORECASE)


def load_frame(path: Path) -> np.ndarray:
    """Load an image as an RGB numpy array."""
    return np.asarray(Image.open(path).convert("RGB"))


def frame_to_qpixmap(frame: np.ndarray) -> QPixmap:
    h, w, _ = frame.shape
    contiguous = np.ascontiguousarray(frame)
    img = QImage(contiguous.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(img)


def auto_frames(folder: Path) -> list[Path]:
    """All auto-saved slide files (NNNNN.png), sorted ascending; marked ones out."""
    files = [p for p in folder.glob("*.png") if _AUTO_FRAME.match(p.name)]
    return sorted(files, key=numeric_key)


class SortFilmstrip(QWidget):
    """Animated film strip for the dedup run.

    The current baseline is always centred; kept baselines stack to the left
    (history stays visible), upcoming candidates queue to the right. The
    candidate (immediately right of centre) gets a red frame when it is about to
    be discarded, then slides out so the rest shift left. Drawn via paintEvent
    with cached thumbnails so it stays fast even at high speed.
    """

    THUMB_W = 116
    THUMB_H = 70
    GAP = 8
    CAP_H = 16

    frame_clicked = Signal(int)  # index into the frames list

    def __init__(self) -> None:
        super().__init__()
        self._frames: list[Path] = []
        self._history: list[int] = []   # kept baselines; last item = current baseline
        self._upcoming: list[int] = []  # not yet processed; [0] = next candidate
        self._discard_pending = False
        self._center: int | None = None  # browse offset; None = follow the baseline
        self._cache: dict[str, QPixmap] = {}
        self.setFixedHeight(self.THUMB_H + self.CAP_H + 12)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_session(self, frames: list[Path]) -> None:
        self._frames = list(frames)
        self._cache.clear()
        self._history = [0] if self._frames else []
        self._upcoming = list(range(1, len(self._frames)))
        self._discard_pending = False
        self._center = None
        self.update()

    # ----- state -----
    def has_candidate(self) -> bool:
        return bool(self._upcoming)

    def baseline_index(self) -> int | None:
        return self._history[-1] if self._history else None

    def candidate_index(self) -> int | None:
        return self._upcoming[0] if self._upcoming else None

    def _seq(self) -> list[int]:
        return self._history + self._upcoming

    def _effective_center(self) -> int:
        if self._center is not None:
            return self._center
        return max(0, len(self._history) - 1)  # baseline position

    def scroll(self, delta: int) -> None:
        seq_len = len(self._history) + len(self._upcoming)
        if seq_len:
            self._center = max(0, min(seq_len - 1, self._effective_center() + delta))
            self.update()

    def center_on(self, frame_index: int) -> None:
        """Centre the cell showing ``frame_index`` (used while browsing, so the
        strip follows the big reference image)."""
        seq = self._seq()
        if frame_index in seq:
            self._center = seq.index(frame_index)
            self.update()

    # ----- transitions (re-follow the baseline) -----
    def mark_discard(self) -> None:
        self._discard_pending = True
        self.update()

    def eject(self) -> int:
        idx = self._upcoming.pop(0)
        self._discard_pending = False
        self._center = None
        self.update()
        return idx

    def rebaseline(self) -> None:
        if self._upcoming:
            self._history.append(self._upcoming.pop(0))
            self._discard_pending = False
            self._center = None
            self.update()

    # ----- click -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        seq = self._seq()
        if not seq:
            return
        step = self.THUMB_W + self.GAP
        pos = self._effective_center() + round((event.position().x() - self.width() / 2) / step)
        if 0 <= pos < len(seq):
            self.frame_clicked.emit(seq[pos])

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
        seq = self._seq()
        if not seq:
            return
        baseline_pos = len(self._history) - 1
        candidate_pos = len(self._history) if self._upcoming else -1
        center = self._effective_center()
        step = self.THUMB_W + self.GAP
        cx = self.width() / 2
        n_side = int((self.width() / 2) // step) + 1
        for pos in range(max(0, center - n_side), min(len(seq), center + n_side + 1)):
            if pos == baseline_pos:
                border = "baseline"
            elif pos == candidate_pos:
                border = "discard" if self._discard_pending else "candidate"
            elif pos < baseline_pos:
                border = "hist"
            else:
                border = "up"
            self._draw_cell(p, cx + (pos - center) * step, seq[pos], border)

    def _draw_cell(self, p: QPainter, center_x: float, idx: int, border: str) -> None:
        x = int(center_x - self.THUMB_W / 2)
        y = 6
        rect = QRect(x, y, self.THUMB_W, self.THUMB_H)
        p.fillRect(rect, QColor(10, 10, 10))
        thumb = self._thumb(idx)
        if thumb is not None:
            p.drawPixmap(x + (self.THUMB_W - thumb.width()) // 2,
                         y + (self.THUMB_H - thumb.height()) // 2, thumb)
        styles = {
            "baseline": (QColor(45, 166, 255), 3),
            "discard": (QColor(230, 40, 40), 4),
            "candidate": (QColor(235, 200, 60), 2),
            "hist": (QColor(70, 70, 70), 1),
            "up": (QColor(70, 70, 70), 1),
        }
        col, w = styles.get(border, (QColor(70, 70, 70), 1))
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
        strip_left = QPushButton("‹")
        strip_left.setFixedWidth(28)
        strip_left.setAutoRepeat(True)
        strip_left.setAutoRepeatInterval(60)
        strip_left.clicked.connect(lambda: self._filmstrip.scroll(-3))
        strip_right = QPushButton("›")
        strip_right.setFixedWidth(28)
        strip_right.setAutoRepeat(True)
        strip_right.setAutoRepeatInterval(60)
        strip_right.clicked.connect(lambda: self._filmstrip.scroll(3))
        strip_row = QHBoxLayout()
        strip_row.setSpacing(4)
        strip_row.addWidget(strip_left)
        strip_row.addWidget(self._filmstrip, stretch=1)
        strip_row.addWidget(strip_right)

        self._speed = QSlider(Qt.Horizontal)
        self._speed.setRange(0, 100)   # 0 = slow (2 s/step), 100 = fast (no delay)
        self._speed.setValue(0)
        self._pause_btn = QPushButton(tr("sort.pause"))
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setVisible(False)
        self._keep_btn = QPushButton(tr("sort.keep"))
        self._keep_btn.clicked.connect(self._override_keep)
        self._keep_btn.setVisible(False)
        self._discard_btn = QPushButton(tr("sort.discard"))
        self._discard_btn.clicked.connect(self._override_discard)
        self._discard_btn.setVisible(False)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel(tr("sort.speed_slow")))
        run_row.addWidget(self._speed, stretch=1)
        run_row.addWidget(QLabel(tr("sort.speed_fast")))
        run_row.addSpacing(12)
        run_row.addWidget(self._pause_btn)
        run_row.addWidget(self._keep_btn)
        run_row.addWidget(self._discard_btn)

        # Action toggle + Start.
        self._action_btn = QPushButton()
        self._action_btn.clicked.connect(self._toggle_action)
        self._run_btn = QPushButton(tr("common.start"))
        self._run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._run_btn.clicked.connect(self._on_run_clicked)
        action_row = QHBoxLayout()
        action_row.addWidget(self._action_btn)
        action_row.addStretch(1)
        action_row.addWidget(self._run_btn)

        self._status = QLabel()

        # Run state.
        self._running = False
        self._paused = False
        self._next_phase = "compare"
        self._removals: list[Path] = []
        self._mask = None
        self._fraction_val = 0.005
        self._baseline_idx: int | None = None
        self._baseline_frame = None
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
        layout.addLayout(run_row)
        layout.addLayout(action_row)
        layout.addWidget(self._status)
        self.resize(960, 860)

        self._update_thr_label(self._thr.value())
        self._refresh_mode_labels()
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
        if not auto_frames(folder) and (folder / "folien").is_dir() and auto_frames(folder / "folien"):
            folder = folder / "folien"
        self._folder = folder
        self._paths = auto_frames(self._folder)
        self._ref_index = 0
        self._path_lbl.setText(self._folder.name)
        self._path_lbl.setToolTip(str(self._folder))
        self.setWindowTitle(f"{APP_NAME} – {tr('hub.sort')} – {self._folder.name}")
        self._apply_saved_config()
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)  # first image centred, rest to the right
        self._status.setText(tr("sort.no_slides") if not self._paths else "")

    # ----- reference image -----
    def _on_strip_click(self, frame_index: int) -> None:
        """Show the clicked film-strip image in the big (reference) view."""
        if 0 <= frame_index < len(self._paths):
            self._ref_index = frame_index
            self._refresh_ref()

    def _show_image_menu(self) -> None:
        """Right-click on the big image: move or delete THE SHOWN slide only
        (manual sorting while browsing — this never starts the automatic run)."""
        if self._running or not self._paths:
            return
        menu = QMenu(self)
        act_move = menu.addAction(tr("sort.menu_move"))
        act_del = menu.addAction(tr("sort.menu_delete"))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_move:
            self._remove_ref(move=True)
        elif chosen == act_del:
            self._remove_ref(move=False)

    def _remove_ref(self, move: bool) -> None:
        """Move (to _aussortiert) or permanently delete the reference image, then
        drop it from the browse list and the film strip."""
        path = self._paths[self._ref_index]
        if move:
            dest = self._folder / "_aussortiert"
            dest.mkdir(exist_ok=True)
            try:
                shutil.move(str(path), str(dest / path.name))
            except OSError:
                return
        else:
            if not ask_yes_no(self, tr("player.delete_title"),
                              tr("player.delete_body", name=path.name)):
                return
            try:
                path.unlink()
            except OSError:
                return
        self._paths.pop(self._ref_index)
        if self._ref_index >= len(self._paths):
            self._ref_index = max(0, len(self._paths) - 1)
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.center_on(self._ref_index)  # keep the shown slide centred

    def _step_ref(self, delta: int) -> None:
        if not self._paths:
            return
        self._ref_index = (self._ref_index + delta) % len(self._paths)
        self._refresh_ref()
        self._filmstrip.center_on(self._ref_index)  # strip follows the big image

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
            self._action_btn.setText(tr("sort.action_delete"))
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
        """Abort the run without applying anything: removals are only executed in
        _finish, so cancelling simply drops the collected list."""
        self._running = False
        self._paused = False
        self._step_timer.stop()
        self._removals = []
        self._set_run_ui(False)
        self._filmstrip.set_session(self._paths)  # back to browse view
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.center_on(self._ref_index)
        self._status.setText(tr("sort.cancelled"))

    def _run(self) -> None:
        if self._running:
            return
        mask = self._current_mask()
        if mask is None or not self._paths:
            QMessageBox.information(self, tr("sort.nothing_title"), tr("sort.nothing_body"))
            return
        if self._action == "delete":
            if not ask_yes_no(self, tr("sort.delete_confirm_title"), tr("sort.delete_confirm_body")):
                return
        set_sortout_config(self._config_dict())
        self._mask = mask
        self._fraction_val = self._fraction()
        self._removals = []
        self._baseline_idx = None
        self._baseline_frame = None
        self._next_phase = "compare"
        self._filmstrip.set_session(self._paths)
        self._running = True
        self._paused = False
        self._set_run_ui(True)
        self._show_baseline_big()  # first reference = first slide
        self._schedule()

    def _show_baseline_big(self) -> None:
        """Show the current baseline (reference) slide as the big image."""
        idx = self._filmstrip.baseline_index()
        if idx is not None and 0 <= idx < len(self._paths):
            self._ref_index = idx
            self._refresh_ref()

    def _schedule(self) -> None:
        if self._running and not self._paused:
            self._step_timer.start(self._delay_ms())

    def _do_phase(self) -> None:
        if not self._running or self._paused:
            return
        if not self._filmstrip.has_candidate():
            self._finish()
            return
        if self._next_phase == "compare":
            base = self._baseline_frame_for(self._filmstrip.baseline_index())
            cand = load_frame(self._paths[self._filmstrip.candidate_index()])
            if masked_frames_differ(base, cand, self._mask, fraction_threshold=self._fraction_val):
                self._filmstrip.rebaseline()  # new baseline
                self._baseline_idx = None
                self._show_baseline_big()     # the new reference appears big
                self._next_phase = "compare"
            else:
                self._filmstrip.mark_discard()  # red frame, eject after the delay
                self._next_phase = "eject"
        else:  # eject the duplicate
            idx = self._filmstrip.eject()
            self._removals.append(self._paths[idx])
            self._next_phase = "compare"
        self._schedule()

    # ----- pause + manual override -----
    def _toggle_pause(self) -> None:
        if not self._running:
            return
        if self._paused:
            self._paused = False
            self._pause_btn.setText(tr("sort.pause"))
            self._set_override_visible(False)
            self._schedule()
        else:
            self._paused = True
            self._step_timer.stop()
            self._pause_btn.setText(tr("common.next"))
            self._set_override_visible(True)

    def _override_keep(self) -> None:
        if not (self._running and self._paused and self._filmstrip.has_candidate()):
            return
        self._filmstrip.rebaseline()
        self._baseline_idx = None
        self._show_baseline_big()
        self._next_phase = "compare"
        if not self._filmstrip.has_candidate():
            self._finish()

    def _override_discard(self) -> None:
        if not (self._running and self._paused and self._filmstrip.has_candidate()):
            return
        idx = self._filmstrip.eject()
        self._removals.append(self._paths[idx])
        self._next_phase = "compare"
        if not self._filmstrip.has_candidate():
            self._finish()

    def _set_override_visible(self, visible: bool) -> None:
        self._keep_btn.setVisible(visible)
        self._discard_btn.setVisible(visible)

    def _set_run_ui(self, running: bool) -> None:
        # The Start button stays enabled: during a run it turns into ABBRECHEN.
        self._run_btn.setText(tr("sort.cancel_run") if running else tr("common.start"))
        self._action_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self._pause_btn.setVisible(running)
        if running:
            self._pause_btn.setText(tr("sort.pause"))
        else:
            self._set_override_visible(False)

    def _finish(self) -> None:
        self._running = False
        self._paused = False
        self._step_timer.stop()
        self._set_run_ui(False)
        removals = self._removals
        if not removals:
            self._status.setText(tr("sort.none_found"))
            return
        if self._action == "move":
            dest = self._folder / "_aussortiert"
            dest.mkdir(exist_ok=True)
            for p in removals:
                try:
                    shutil.move(str(p), str(dest / p.name))
                except OSError:
                    pass
            done = tr("sort.moved", n=len(removals))
        else:
            for p in removals:
                try:
                    p.unlink()
                except OSError:
                    pass
            done = tr("sort.deleted", n=len(removals))

        self._paths = auto_frames(self._folder)
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._status.setText(tr("sort.remaining", done=done, n=len(self._paths)))


def open_sorter(folder: Path | None = None) -> SortOutWindow:
    """Open the sort-out window; the folder is chosen inside the window."""
    win = SortOutWindow(folder)
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
