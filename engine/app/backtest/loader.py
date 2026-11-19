"""Doc du lieu cho backtest: 1m parquet -> 15m/1h/4h, filter san, funding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..data import bars as bars_mod
from ..data import parquet_io

DEFAULT_FILTERS = {"step_size": 0.001, "tick_size": 0.01, "min_notional": 5.0}


def load_1m(root: str | Path, symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Doc cac partition ngay trong [start_ms, end_ms); sap xep, bo nen chua dong."""
    by_ts: dict[int, dict[str, Any]] = {}
    for day in parquet_io.list_days(root, symbol, "1m"):
        rows = parquet_io.load_day(root, symbol, "1m", day)
        if not rows:
            continue
        if rows[-1]["open_time"] < start_ms or rows[0]["open_time"] >= end_ms:
            continue
        for r in rows:
            ts = int(r["open_time"])
            if start_ms <= ts < end_ms and r.get("closed", True):
                by_ts[ts] = r
    return [by_ts[k] for k in sorted(by_ts)]


def aggregate(bars_1m: list[dict[str, Any]], tf: str) -> list[dict[str, Any]]:
    tf_bars, _gaps = bars_mod.aggregate(bars_1m, tf)
    return tf_bars


def load_filters(path: str | Path) -> dict[str, dict[str, float]]:
    """symbol -> step_size/tick_size/min_notional tu exchangeInfo (fixture hoac cache)."""

    p = Path(path)
    if not p.is_file():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, dict[str, float]] = {}
    for sym in raw.get("symbols", []):
        rec = dict(DEFAULT_FILTERS)
        for f in sym.get("filters", []):
            kind = f.get("filterType")
            if kind == "LOT_SIZE":
                rec["step_size"] = float(f.get("stepSize", rec["step_size"]))
            elif kind == "PRICE_FILTER":
                rec["tick_size"] = float(f.get("tickSize", rec["tick_size"]))
            elif kind == "MIN_NOTIONAL":
                rec["min_notional"] = float(f.get("notional", rec["min_notional"]))
        out[str(sym["symbol"])] = rec
    return out


def slice_1m(bars: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    return [b for b in bars if start_ms <= int(b["open_time"]) < end_ms]
