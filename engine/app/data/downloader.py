"""Downloader P1.2: bulk data.binance.vision + backfill REST, luu Parquet/symbol/ngay.

Chi dung stdlib + callable de test gia lap (CI offline). Parquet neu co
pyarrow, neu khong fallback JSONL. Khong dung nen chua dong.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from typing import Callable

BULK_FMT = (
    "https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1m/{symbol}-1m-{date}.zip"
)
REST_LIMIT = 1000


def bulk_url(symbol: str, date_str: str) -> str:
    """URL bulk ngay YYYY-MM-DD."""
    return BULK_FMT.format(symbol=symbol, date=date_str)


def parse_rest_klines(rows: list) -> list[dict]:
    """Chuan hoa kline REST thanh bar 1m da dong."""
    return [
        {
            "open_time": int(r[0]),
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
            "v": float(r[5]),
            "close_time": int(r[6]),
            "closed": True,
        }
        for r in rows
    ]


def parse_bulk_csv(text: str) -> list[dict]:
    """CSV trong zip bulk: openTime,o,h,l,c,v,closeTime,... ."""
    out: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        p = line.split(",")
        out.append(
            {
                "open_time": int(p[0]),
                "o": float(p[1]),
                "h": float(p[2]),
                "l": float(p[3]),
                "c": float(p[4]),
                "v": float(p[5]),
                "close_time": int(p[6]),
                "closed": True,
            }
        )
    return out


def save_day(root: str, symbol: str, date_str: str, bars: list[dict]) -> str:
    """Luu 1 ngay, tra ve path thuc te (.parquet neu co pyarrow, .jsonl neu khong)."""
    d = os.path.join(root, symbol)
    os.makedirs(d, exist_ok=True)
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = os.path.join(d, f"{date_str}.parquet")
        pq.write_table(pa.Table.from_pylist(bars), path)
        return path
    except Exception:
        path = os.path.join(d, f"{date_str}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for b in bars:
                f.write(json.dumps(b) + "\n")
        return path


def load_day(root: str, symbol: str, date_str: str) -> list[dict]:
    pq_path = os.path.join(root, symbol, f"{date_str}.parquet")
    js_path = os.path.join(root, symbol, f"{date_str}.jsonl")
    if os.path.exists(pq_path):
        try:
            import pyarrow.parquet as pq

            return pq.read_table(pq_path).to_pylist()
        except Exception:
            pass
    if os.path.exists(js_path):
        with open(js_path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    return []


def fetch_bulk_day(symbol: str, date_str: str, get_bytes: Callable[[str], bytes]) -> list[dict]:
    """Tai 1 ngay bulk (get_bytes de test, that dung httpx)."""
    raw = get_bytes(bulk_url(symbol, date_str))
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return parse_bulk_csv(z.read(z.namelist()[0]).decode())


def backfill(rest_get: Callable[..., list], symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """Backfill xuoi thoi gian bang REST klines, chong lap vo han."""
    out: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        rows = rest_get(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": "1m", "startTime": cur,
             "endTime": end_ms, "limit": REST_LIMIT},
            signed=False,
        )
        if not rows:
            break
        bars = parse_rest_klines(rows)
        out.extend(bars)
        nxt = bars[-1]["open_time"] + 60_000
        if nxt <= cur:
            break
        cur = nxt
        if len(rows) < REST_LIMIT:
            break
    return out
