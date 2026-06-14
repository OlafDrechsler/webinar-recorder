import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.slide_dedupe import build_compare_mask, Region, RECT, ELLIPSE, IGNORE

# Ellipse extends past the left/bottom edge; rectangle overlaps it.
regs = [Region(ELLIPSE, -30, 40, 120, 120), Region(RECT, 0, 70, 40, 60)]
m = build_compare_mask(100, 100, regs, IGNORE)
print("no error, mask shape:", m.shape)
print("ignored pixels (False):", int((~m).sum()), "of", m.size)
print("bottom-left ignored:", not m[95, 5])
print("top-right still compared:", m[5, 95])
