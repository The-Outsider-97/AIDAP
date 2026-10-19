"""Launcher that works from any directory:  ``python run.py check``  /  ``python run.py serve``.

``python -m AIDAP`` needs the *parent* folder (SLAI/applications) on the path; this file puts it there itself,
so it also works when you are standing inside the AIDAP folder. Every command of ``python -m AIDAP`` is available.
"""

from __future__ import annotations

import sys
from pathlib import Path

PARENT = str(Path(__file__).resolve().parent.parent)          # <SLAI>/applications
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from AIDAP.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
