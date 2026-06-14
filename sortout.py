"""Launcher for the slide-deduplication tool. See gui/sort_out.py.

Run:  python sortout.py  [folder]   (or use the "Folien aussortieren" shortcut)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.sort_out import main

if __name__ == "__main__":
    raise SystemExit(main())
