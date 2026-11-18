"""Downloader P1.2: bulk data.binance.vision (monthly + daily) va backfill REST.

- Monthly cho thang da ket thuc, daily cho thang hien tai / moc le.
- Verify .CHECKSUM (sha256) khi co; khong co thi bo qua kem warning.
- Normalize timestamp ve mili-giay (bulk co luc tra ve microsecond).
- Chi luu nen da dong, dedupe theo open_time, sap xep tang dan.
"""

from __future__ import annotations

import hashlib
import io
import time
import zipfile
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from . import parquet_io

BULK_DAILY = (
    "https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1m/{symbol}-1m-{date}.zip"
)
BULK_MONTHLY = (
    "https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip"
)
REST_LIMIT = 1000
DAY_MS = 86_400_000


def bulk_url(symbol: str, date_str: str) -> str:
    """URL bulk ngay YYYY-MM-DD (giu ten cu de khong pha test P1.0)."""
    return BULK_DAILY.format(symbol=symbol, date=date_str)


def bulk_url_monthly(symbol: str, month: str) -> str:
    """URL bulk thang YYYY-MM."""
    return BULK_MONTHLY.format(symbol=symbol, month=month)


def normalize_ts(v: Any) -> int:
    """Bulk co the tra microsecond (19 chu so) -> doi ve ms; REST luon la ms."""
    ts = int(v)
    if ts > 10**14:
        return ts // 1000
    return ts


def parse_bulk_csv(text: str) -> list[dict]:
    """CSV trong zip: co the co dong header (moi) hoac khong (cu)."""
    by_ts: dict[int, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        p = line.split(",")
        if not p[0].strip().lstrip("-").isdigit():
            continue  # header: open_time,open,high,...
        ot = normalize_ts(p[0])
        by_ts[ot] = {
            "open_time": ot,
            "o": float(p[1]),
            "h": float(p[2]),
            "l": float(p[3]),
            "c": float(p[4]),
            "v": float(p[5]),
            "close_time": normalize_ts(p[6]),
            "closed": True,
        }
    return [by_ts[k] for k in sorted(by_ts)]


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


def split_by_day(bars: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for b in bars:
        d = time.strftime("%Y-%m-%d", time.gmtime(b["open_time"] // 1000))
        out.setdefault(d, []).append(b)
    return out


def parse_checksum(text: str) -> str:
    """Dong dau .CHECKSUM cua Binance: '<sha256>  <ten file>'."""
    first = text.strip().splitlines()[0].strip()
    return first.split()[0].lower()


def _month_bounds(start: date, end: date) -> Iterable[tuple[date, date]]:
    """Cac thang tron ven nam trong [start, end] (end la ngay cuoi cung)."""
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        last = nxt - timedelta(days=1)
        if cur >= start and last <= end:
            yield cur, last
        cur = nxt


def _days(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def http_fetch(url: str, timeout: float = 30.0, retries: int = 3) -> bytes:
    """GET co retry/backoff cho 429/5xx. 404 tra ngay de caller bo qua."""
    import httpx

    last: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                r = c.get(url)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r.content
        except FileNotFoundError:
            raise
        except Exception as e:  # mang/5xx/429: thu lai voi backoff
            last = e
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"tai that bai: {url}: {last}")


class BulkFetcher:
    """Tai + verify + luu partition. Idempotent: partition da co thi bo qua."""

    def __init__(
        self,
        root: str,
        get_bytes: Callable[[str], bytes] | None = None,
        log: Callable[[str], None] = print,
        verify: bool = True,
    ) -> None:
        self.root = root
        self.get_bytes = get_bytes or http_fetch
        self.log = log
        self.verify = verify
        self.files = 0
        self.skipped = 0
        self.missing: list[str] = []

    def _fetch_zip(self, url: str) -> list[dict]:
        raw = self.get_bytes(url)
        if self.verify:
            try:
                expected = parse_checksum(self.get_bytes(url + ".CHECKSUM").decode())
                got = hashlib.sha256(raw).hexdigest()
                if expected != got:
                    raise ValueError(f"CHECKSUM lech: {url}")
            except FileNotFoundError:
                self.log(f"warn checksum thieu: {url}")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return parse_bulk_csv(z.read(z.namelist()[0]).decode())

    def _save(
        self, symbol: str, start: date, end: date, bars: list[dict], existing: set[str]
    ) -> None:
        for d, rows in sorted(split_by_day(bars).items()):
            day = date.fromisoformat(d)
            if day < start or day > end:
                continue
            if d in existing:
                self.skipped += 1
                continue
            parquet_io.save_day(self.root, symbol, "1m", d, rows)
            existing.add(d)
            self.files += 1

    def download(self, symbol: str, start: date, end: date) -> dict:
        """Tai [start, end]. Thang tron ven dung bulk thang, con lai dung daily."""
        before_files, before_skip = self.files, self.skipped
        daily_done: set[date] = set()
        existing = set(parquet_io.list_days(self.root, symbol, "1m"))
        for first, _last in _month_bounds(start, end):
            month = f"{first.year:04d}-{first.month:02d}"
            try:
                bars = self._fetch_zip(bulk_url_monthly(symbol, month))
            except FileNotFoundError:
                self.missing.append(f"monthly:{symbol}:{month}")
                continue
            self._save(symbol, start, end, bars, existing)
            daily_done.update(date.fromisoformat(d) for d in split_by_day(bars))

        for day in _days(start, end):
            if day in daily_done:
                continue
            ds = day.isoformat()
            if ds in existing:
                self.skipped += 1
                continue
            try:
                bars = self._fetch_zip(bulk_url(symbol, ds))
            except FileNotFoundError:
                self.missing.append(f"daily:{symbol}:{ds}")
                continue
            self._save(symbol, day, day, bars, existing)
        return {
            "symbol": symbol,
            "files": self.files - before_files,
            "skipped": self.skipped - before_skip,
            "missing": len(self.missing),
        }


def backfill(rest_get: Callable[..., list], symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """Backfill xuoi thoi gian bang REST klines, chong lap vo han."""
    out: list[dict] = []
    seen: set[int] = set()
    cur = start_ms
    while cur < end_ms:
        rows = rest_get(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "1m",
                "startTime": cur,
                "endTime": end_ms,
                "limit": REST_LIMIT,
            },
            signed=False,
        )
        if not rows:
            break
        bars = parse_rest_klines(rows)
        for b in bars:
            if b["open_time"] not in seen:
                seen.add(b["open_time"])
                out.append(b)
        nxt = bars[-1]["open_time"] + 60_000
        if nxt <= cur:
            break
        cur = nxt
        if len(rows) < REST_LIMIT:
            break
    return out
