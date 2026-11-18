"""Doc/ghi Parquet cho pipeline P1.2.

Ghi atomic (file tam + os.replace) de replay khong bao gio doc phai file do dang.
Partition theo symbol/tf/ngay, dung pyarrow; khong dung pandas/numpy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

FIELDS = ("open_time", "close_time", "o", "h", "l", "c", "v", "closed")


def _schema():  # type: ignore[no-untyped-def]
    import pyarrow as pa

    return pa.schema(
        [
            ("open_time", pa.int64()),
            ("close_time", pa.int64()),
            ("o", pa.float64()),
            ("h", pa.float64()),
            ("l", pa.float64()),
            ("c", pa.float64()),
            ("v", pa.float64()),
            ("closed", pa.bool_()),
        ]
    )


def day_path(root: str | Path, symbol: str, tf: str, date_str: str) -> Path:
    return Path(root) / symbol / tf / f"{date_str}.parquet"


def normalize_bars(bars: list[dict]) -> list[dict]:
    """Sap xep + dedupe theo open_time (giu ban ghi cuoi), bo du lieu thieu field."""
    by_ts: dict[int, dict] = {}
    for b in bars:
        try:
            ts = int(b["open_time"])
        except (KeyError, TypeError, ValueError):
            continue
        by_ts[ts] = {
            "open_time": ts,
            "close_time": int(b.get("close_time") or ts + 59_999),
            "o": float(b["o"]),
            "h": float(b["h"]),
            "l": float(b["l"]),
            "c": float(b["c"]),
            "v": float(b.get("v") or 0.0),
            "closed": bool(b.get("closed", True)),
        }
    return [by_ts[k] for k in sorted(by_ts)]


def save_day(root: str | Path, symbol: str, tf: str, date_str: str, bars: list[dict]) -> Path:
    """Ghi 1 partition ngay. Tra ve path; khong ghi neu bars rong."""
    rows = normalize_bars(bars)
    if not rows:
        raise ValueError(f"khong co bar de ghi: {symbol} {tf} {date_str}")
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = day_path(root, symbol, tf, date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrs = {f: [r[f] for r in rows] for f in FIELDS}
    table = pa.Table.from_pydict(arrs, schema=_schema())
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="snappy")
    os.replace(tmp, path)  # atomic: replay chi thay file hoan chinh
    return path


def load_day(root: str | Path, symbol: str, tf: str, date_str: str) -> list[dict]:
    import pyarrow.parquet as pq

    path = day_path(root, symbol, tf, date_str)
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def list_days(root: str | Path, symbol: str, tf: str) -> list[str]:
    d = Path(root) / symbol / tf
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.parquet"))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
