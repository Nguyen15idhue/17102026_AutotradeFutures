"""Ghi bars/features/regime vao SQLite P1.2. Idempotent, batch, 1 transaction.

Python la writer duy nhat (AGENTS §7); khong dung chung connection voi WS/reconcile.
"""

from __future__ import annotations

import sqlite3

from ..regime.types import RegimeResult

_FEATURE_COLS = (
    "atr",
    "adx",
    "bb_mid",
    "bb_up",
    "bb_dn",
    "bbw",
    "bbw_pct",
    "z",
    "vol_pct",
    "range_24h",
    "range_pos",
    "ema50",
    "ema200",
    "oi",
    "funding",
)


def _tx(con: sqlite3.Connection):
    class _Ctx:
        def __enter__(self) -> sqlite3.Connection:
            con.execute("BEGIN")
            return con

        def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            if exc_type is None:
                con.execute("COMMIT")
            else:
                con.execute("ROLLBACK")
            return False

    return _Ctx()


def upsert_bars(con: sqlite3.Connection, symbol: str, tf: str, bars: list[dict]) -> int:
    rows = [
        (
            symbol,
            tf,
            int(b["open_time"]),
            float(b["o"]),
            float(b["h"]),
            float(b["l"]),
            float(b["c"]),
            float(b.get("v") or 0.0),
            int(bool(b.get("closed", True))),
        )
        for b in bars
    ]
    with _tx(con):
        con.executemany(
            "INSERT INTO bars(symbol,tf,open_time,o,h,l,c,v,closed) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol,tf,open_time) DO UPDATE SET "
            "o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v,"
            "closed=excluded.closed",
            rows,
        )
    return len(rows)


def upsert_features(con: sqlite3.Connection, symbol: str, tf: str, feats: list[dict | None]) -> int:
    rows = []
    for f in feats:
        if not f:
            continue
        rows.append(
            (
                symbol,
                tf,
                int(f["ts"]),
                *[f.get(c) for c in _FEATURE_COLS],
                int(bool(f.get("allow_mr"))),
            )
        )
    cols = "symbol,tf,ts," + ",".join(_FEATURE_COLS) + ",allow_mr"
    marks = ",".join(["?"] * (len(_FEATURE_COLS) + 4))
    updates = ",".join(f"{c}=excluded.{c}" for c in _FEATURE_COLS) + ",allow_mr=excluded.allow_mr"
    with _tx(con):
        con.executemany(
            f"INSERT INTO features({cols}) VALUES({marks}) "
            f"ON CONFLICT(symbol,tf,ts) DO UPDATE SET {updates}",
            rows,
        )
    return len(rows)


def upsert_regime(
    con: sqlite3.Connection, symbol: str, rows: list[tuple[int, RegimeResult]]
) -> int:
    data = [
        (symbol, int(ts), r.label.value, float(r.confidence), r.raw_label.value, r.reason)
        for ts, r in rows
    ]
    with _tx(con):
        con.executemany(
            "INSERT INTO regime(symbol,ts,label,confidence,raw_label,reason) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(symbol,ts) DO UPDATE SET "
            "label=excluded.label,confidence=excluded.confidence,"
            "raw_label=excluded.raw_label,reason=excluded.reason",
            data,
        )
    return len(data)


def read_regime(con: sqlite3.Connection, symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    cur = con.execute(
        "SELECT ts,label,confidence,raw_label,reason FROM regime "
        "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts",
        (symbol, start_ms, end_ms),
    )
    return [
        {"ts": r[0], "label": r[1], "confidence": r[2], "raw_label": r[3], "reason": r[4]}
        for r in cur.fetchall()
    ]


def read_features(
    con: sqlite3.Connection, symbol: str, tf: str, start_ms: int, end_ms: int
) -> list[dict]:
    cols = "ts," + ",".join(_FEATURE_COLS) + ",allow_mr"
    cur = con.execute(
        f"SELECT {cols} FROM features WHERE symbol=? AND tf=? AND ts>=? AND ts<=? ORDER BY ts",
        (symbol, tf, start_ms, end_ms),
    )
    return [dict(zip(cols.split(","), r)) for r in cur.fetchall()]
