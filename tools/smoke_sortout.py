"""Headless smoke test for the slide-deduplication tool."""

import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from core.slide_dedupe import RECT
from gui.sort_out import SortOutWindow

d = Path(tempfile.mkdtemp())
for i in range(5):
    f = np.zeros((40, 40, 3), dtype=np.uint8)
    f[:, 0:20] = (i * 40) % 256  # speaker area churns (left half)
    Image.fromarray(f).save(d / f"{i:05d}.png")
# marked annotation must be ignored entirely
Image.fromarray(np.zeros((40, 40, 3), np.uint8)).save(d / "00002_markiert_01.png")

app = QApplication([])
w = SortOutWindow(d)
print("Auto frames found:", [p.name for p in w._paths])
w._canvas.set_regions([{"shape": RECT, "left": 0, "top": 0, "width": 20, "height": 40}])
w._action = "move"
w._run()

moved = sorted(p.name for p in (d / "_aussortiert").glob("*.png")) if (d / "_aussortiert").is_dir() else []
remaining = sorted(p.name for p in d.glob("*.png"))
print("Moved to _aussortiert:", moved)
print("Remaining in folder :", remaining)
print("Marked file untouched:", (d / "00002_markiert_01.png").exists())
print("RESULT:", "PASS" if moved == ["00001.png", "00002.png", "00003.png", "00004.png"]
      and (d / "00002_markiert_01.png").exists() else "FAIL")
