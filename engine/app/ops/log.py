"""Log ra stdout. Khong bao gio in secret (AGENTS.md §7)."""

from __future__ import annotations

import json
import sys
import time

_MASK_KEYS = ("token", "secret", "signature", "listenkey", "listenKey", "apikey")


def _scrub(obj):
    if isinstance(obj, dict):
        return {
            k: ("***" if any(m in str(k).lower() for m in _MASK_KEYS) else _scrub(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def log(level: str, event: str, **fields) -> None:
    rec = {"ts": int(time.time() * 1000), "level": level, "event": event, **_scrub(fields)}
    sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stdout.flush()
