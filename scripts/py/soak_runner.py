"""Wrapper tuong thich: goi engine/app/soak.py (logic that da chuyen vao engine).

Dung truc tiep: python -m app.soak (tu thu muc engine) hoac service compose `soak`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from app.soak import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
