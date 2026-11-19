"""Funding history cho backtest (00/08/16 UTC).

Nguon: data.binance.vision (monthly/daily fundingRate). Khong co mang -> tra ve {}
va caller dung hang so 1 bp/8h, ghi ro trong report. Khong bao gio doan funding = 0
ma khong ghi: funding am la thu lam short trong downtrend manh mat tien that.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

MONTHLY = (
    "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
    "{sym}/{sym}-fundingRate-{stamp}.zip"
)
DAILY = (
    "https://data.binance.vision/data/futures/um/daily/fundingRate/"
    "{sym}/{sym}-fundingRate-{stamp}.zip"
)


def _parse_zip(payload: bytes) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            if not name.endswith(".csv"):
                continue
            text = zf.read(name).decode("utf-8")
            for row in csv.reader(io.StringIO(text)):
                if len(row) < 3:
                    continue
                try:
                    ts = int(float(row[0]))
                    if ts < 10**12:  # mot so file ghi giay thay vi ms
                        ts *= 1000
                    rate = float(row[2])
                except ValueError:
                    continue  # header
                out.append((ts, rate))
    return out


def fetch(symbol: str, start: date, end: date, timeout: float = 30.0) -> dict[int, float]:
    """Tai funding trong [start, end]; loi mang -> {} (caller fallback)."""

    from ..data.downloader import http_fetch

    out: dict[int, float] = {}
    cur = date(start.year, start.month, 1)
    last_full_month = date(end.year, end.month, 1)
    while cur < last_full_month:
        url = MONTHLY.format(sym=symbol, stamp=f"{cur.year:04d}-{cur.month:02d}")
        try:
            for ts, rate in _parse_zip(http_fetch(url, timeout=timeout)):
                out[ts] = rate
        except Exception:
            pass
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    day = last_full_month
    while day <= end:
        url = DAILY.format(sym=symbol, stamp=day.isoformat())
        try:
            for ts, rate in _parse_zip(http_fetch(url, timeout=timeout)):
                out[ts] = rate
        except Exception:
            pass
        day += timedelta(days=1)
    return out


def load_or_fetch(
    root: str | Path, symbol: str, start: date, end: date
) -> tuple[dict[int, float], bool]:
    """Doc cache data/funding/{symbol}.json; tai/gop them neu cache khong phu khoang.

    Tra (rates, co_du_lieu). `co_du_lieu=False` -> caller fallback hang so va ghi ro
    trong report; khong duoc im lang coi funding = 0.
    """

    import calendar

    d = Path(root) / "funding"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{symbol}.json"
    start_ms = int(calendar.timegm(start.timetuple())) * 1000
    end_ms = int(calendar.timegm(end.timetuple())) * 1000

    def _aligned(raw: dict) -> dict[int, float]:
        return {int(k) - int(k) % 60_000: float(v) for k, v in raw.items()}

    if p.is_file():
        cached = _aligned(json.loads(p.read_text(encoding="utf-8")))
        if cached and min(cached) <= start_ms and max(cached) >= end_ms - 28_800_000:
            return cached, True
        merged = dict(cached)
        merged.update({ts - ts % 60_000: float(v) for ts, v in fetch(symbol, start, end).items()})
        if merged:
            p.write_text(
                json.dumps({str(k): v for k, v in sorted(merged.items())}), encoding="utf-8"
            )
        return merged, bool(merged)
    rates = fetch(symbol, start, end)
    aligned = {ts - ts % 60_000: float(v) for ts, v in sorted(rates.items())}
    if aligned:
        p.write_text(json.dumps({str(k): v for k, v in sorted(aligned.items())}), encoding="utf-8")
    return aligned, bool(aligned)
