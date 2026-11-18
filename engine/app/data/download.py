"""CLI tai du lieu P1.2: python -m app.data.download --symbols ... --start ... --end ...

Vi du:
    python -m app.data.download --symbols BTCUSDT,ETHUSDT,SOLUSDT \
        --start 2026-06-01 --end 2026-11-15 --data-dir data/market
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from . import downloader, parquet_io
from .downloader import BulkFetcher, backfill


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def missing_days(root: str, symbol: str, start: date, end: date) -> list[date]:
    have = set(parquet_io.list_days(root, symbol, "1m"))
    out, cur = [], start
    while cur <= end:
        if cur.isoformat() not in have:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def rest_backfill(root: str, symbol: str, start: date, end: date) -> int:
    """Backfill cac ngay thieu bang REST (mock/live). Tra ve so ngay ghi duoc."""
    from ..exchange import rest as rest_mod

    base = os.environ.get("BINANCE_BASE_URL", "http://binance-demo-server:8080")
    key = os.environ.get("BINANCE_API_KEY") or os.environ.get("MOCK_API_KEY", "verify-key")
    secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get(
        "MOCK_API_SECRET", "mock-secret"
    )
    client = rest_mod.RestClient(base, key, secret)
    wrote = 0
    for day in missing_days(root, symbol, start, end):
        s_ms = int(calendar.timegm(day.timetuple())) * 1000
        e_ms = s_ms + downloader.DAY_MS
        bars = backfill(client.get, symbol, s_ms, e_ms)
        if not bars:
            continue
        parquet_io.save_day(root, symbol, "1m", day.isoformat(), bars)
        wrote += 1
    return wrote


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tai klines 1m bulk cho P1.2")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (bao gom)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (bao gom)")
    ap.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    ap.add_argument("--no-verify", action="store_true", help="bo qua .CHECKSUM (chi khi debug)")
    ap.add_argument(
        "--rest-backfill", action="store_true", help="backfill ngay thieu bang REST (mock/live)"
    )
    args = ap.parse_args(argv)

    root = Path(args.data_dir) / "market"
    start, end = _parse_date(args.start), _parse_date(args.end)
    if end < start:
        ap.error("--end phai >= --start")
    if end > date.today():
        end = date.today()

    t0 = time.time()
    summary: dict = {"start": start.isoformat(), "end": end.isoformat(), "symbols": {}}
    fetcher = BulkFetcher(str(root), verify=not args.no_verify)
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        stat = fetcher.download(sym, start, end)
        if args.rest_backfill:
            stat["rest_days"] = rest_backfill(str(root), sym, start, end)
        files = parquet_io.list_days(str(root), sym, "1m")
        bars = sum(len(parquet_io.load_day(root, sym, "1m", d)) for d in files)
        size = sum((root / sym / "1m" / f"{d}.parquet").stat().st_size for d in files)
        stat.update(days=len(files), bars=bars, parquet_mb=round(size / 1e6, 2))
        summary["symbols"][sym] = stat
        print(
            f"symbol={sym} days={stat['days']} bars={bars} "
            f"new={stat['files']} skipped={stat['skipped']} "
            f"missing={stat['missing']} parquet_mb={stat['parquet_mb']}",
            flush=True,
        )

    summary["missing"] = fetcher.missing
    summary["elapsed_s"] = round(time.time() - t0, 1)
    rep = Path(args.data_dir) / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "p1.2-download.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"download.done elapsed_s={summary['elapsed_s']} report={rep / 'p1.2-download.json'}")
    return 0 if not fetcher.missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
