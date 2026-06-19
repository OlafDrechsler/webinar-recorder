"""Slide-deduplication tool ("Folien aussortieren").

Post-processes a folder of slide screenshots: you mark the speaker area on a
reference image as an ignore region (rectangle or ellipse), and the tool walks
the images in ascending number order, removing those that are identical to the
previous kept image *outside* that region. The first of each identical run is
always kept.

Workflow (see also core/slide_dedupe.py for the comparison logic):
1. Pick the (pre-sorted) folder.
2. Draw one or more ignore regions on a reference image; step through images to
   find a representative one. Rectangle or ellipse; mode Ignorieren/Vergleichen.
3. Set the sensitivity, run "Probelauf" to see how many would be removed.
4. Toggle Aussortieren (move to ``_aussortiert``) vs. Endgültig löschen, then Start.

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
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.settings import get_data_dir, get_sortout_config, set_sortout_config
from gui.branding import APP_NAME, app_icon
from core.slide_dedupe import (
    COMPARE,
    ELLIPSE,
    IGNORE,
    RECT,
    Region,
    build_compare_mask,
    numeric_key,
    plan_deletions,
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


class _Cancelled(Exception):
    pass


class MaskCanvas(QWidget):
    """Shows a reference image and lets the user draw rectangle/ellipse regions."""

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
    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = Path(folder)
        self._paths = auto_frames(self._folder)
        self._ref_index = 0
        self._mask_mode = IGNORE
        self._action = "move"  # "move" or "delete"
        self.setWindowTitle(f"{APP_NAME} – Folien aussortieren – {self._folder.name}")
        self.setWindowIcon(app_icon())

        self._canvas = MaskCanvas()
        self._ref_label = QLabel()

        # Reference-image stepping.
        prev_btn = QPushButton("‹ vorheriges")
        prev_btn.clicked.connect(lambda: self._step_ref(-1))
        next_btn = QPushButton("nächstes ›")
        next_btn.clicked.connect(lambda: self._step_ref(1))
        ref_row = QHBoxLayout()
        ref_row.addWidget(prev_btn)
        ref_row.addWidget(self._ref_label, stretch=1)
        ref_row.addWidget(next_btn)

        # Drawing tools.
        rect_btn = QPushButton("Rechteck")
        rect_btn.clicked.connect(lambda: self._canvas.set_tool(RECT))
        ell_btn = QPushButton("Ellipse")
        ell_btn.clicked.connect(lambda: self._canvas.set_tool(ELLIPSE))
        undo_btn = QPushButton("Letzten Bereich entfernen")
        undo_btn.clicked.connect(self._canvas.undo)
        clear_btn = QPushButton("Alle löschen")
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
        save_btn = QPushButton("Maske speichern…")
        save_btn.clicked.connect(self._save_mask_file)
        load_btn = QPushButton("Maske laden…")
        load_btn.clicked.connect(self._load_mask_file)
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("Empfindlichkeit:"))
        thr_row.addWidget(self._thr, stretch=1)
        thr_row.addWidget(self._thr_label)
        thr_row.addWidget(save_btn)
        thr_row.addWidget(load_btn)

        # Actions.
        self._action_btn = QPushButton()
        self._action_btn.clicked.connect(self._toggle_action)
        dry_btn = QPushButton("Probelauf")
        dry_btn.clicked.connect(self._dry_run)
        run_btn = QPushButton("Start")
        run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        run_btn.clicked.connect(self._run)
        action_row = QHBoxLayout()
        action_row.addWidget(self._action_btn)
        action_row.addStretch(1)
        action_row.addWidget(dry_btn)
        action_row.addWidget(run_btn)

        self._status = QLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(ref_row)
        layout.addWidget(self._canvas, stretch=1)
        layout.addLayout(tools)
        layout.addLayout(thr_row)
        layout.addLayout(action_row)
        layout.addWidget(self._status)
        self.resize(900, 720)

        self._apply_saved_config()
        self._refresh_ref()
        self._update_thr_label(self._thr.value())
        self._refresh_mode_labels()
        if not self._paths:
            self._status.setText("Keine Folienbilder (NNNNN.png) in diesem Ordner gefunden.")

    # ----- reference image -----
    def _step_ref(self, delta: int) -> None:
        if not self._paths:
            return
        self._ref_index = (self._ref_index + delta) % len(self._paths)
        self._refresh_ref()

    def _refresh_ref(self) -> None:
        if not self._paths:
            self._ref_label.setText("—")
            return
        path = self._paths[self._ref_index]
        self._canvas.set_base(frame_to_qpixmap(load_frame(path)))
        self._ref_label.setText(
            f"Referenzbild {self._ref_index + 1}/{len(self._paths)}: {path.name}"
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
            "Modus: Ignorierbereich" if self._mask_mode == IGNORE else "Modus: Vergleichsbereich"
        )
        if self._action == "move":
            self._action_btn.setText("Aktion: Aussortieren (verschieben)")
            self._action_btn.setStyleSheet("")
        else:
            self._action_btn.setText("Aktion: ENDGÜLTIG LÖSCHEN")
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
        name, _ = QFileDialog.getSaveFileName(self, "Maske speichern", "", "JSON (*.json)")
        if name:
            Path(name).write_text(json.dumps(self._config_dict(), indent=2), encoding="utf-8")

    def _load_mask_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Maske laden", "", "JSON (*.json)")
        if name:
            try:
                self._apply_config(json.loads(Path(name).read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Laden fehlgeschlagen", str(exc))

    # ----- run -----
    def _plan(self) -> list[Path] | None:
        mask = self._current_mask()
        if mask is None or not self._paths:
            QMessageBox.information(self, "Nichts zu tun", "Keine Bilder vorhanden.")
            return None
        set_sortout_config(self._config_dict())  # remember mask for next time

        dialog = QProgressDialog("Vergleiche Bilder…", "Abbrechen", 0, len(self._paths), self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)

        def progress(done: int, total: int) -> None:
            dialog.setValue(done)
            QApplication.processEvents()
            if dialog.wasCanceled():
                raise _Cancelled()

        try:
            removals = plan_deletions(
                self._paths, load_frame, mask, fraction_threshold=self._fraction(),
                progress=progress,
            )
        except _Cancelled:
            dialog.close()
            return None
        dialog.close()
        return removals

    def _dry_run(self) -> None:
        removals = self._plan()
        if removals is None:
            return
        self._status.setText(
            f"Probelauf: {len(removals)} von {len(self._paths)} Bildern wären Duplikate "
            f"(es bliebe(n) {len(self._paths) - len(removals)})."
        )

    def _run(self) -> None:
        if self._action == "delete":
            confirm = QMessageBox.question(
                self, "Endgültig löschen?",
                "Die als Duplikat erkannten Bilder werden UNWIDERRUFLICH gelöscht.\n"
                "Fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        removals = self._plan()
        if removals is None:
            return
        if not removals:
            self._status.setText("Keine Duplikate gefunden – nichts geändert.")
            return

        if self._action == "move":
            dest = self._folder / "_aussortiert"
            dest.mkdir(exist_ok=True)
            for p in removals:
                try:
                    shutil.move(str(p), str(dest / p.name))
                except OSError:
                    pass
            done = f"{len(removals)} Bilder nach '_aussortiert' verschoben."
        else:
            for p in removals:
                try:
                    p.unlink()
                except OSError:
                    pass
            done = f"{len(removals)} Bilder endgültig gelöscht."

        self._paths = auto_frames(self._folder)
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._status.setText(f"{done} Verbleibend: {len(self._paths)}.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
    else:
        start = str(get_data_dir())
        chosen = QFileDialog.getExistingDirectory(None, "Folienordner wählen", start)
        if not chosen:
            return 0
        folder = Path(chosen)
    win = SortOutWindow(folder)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
