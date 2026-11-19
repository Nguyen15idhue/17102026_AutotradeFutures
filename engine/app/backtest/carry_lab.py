"""Phòng thử funding carry delta-neutral (P1.4c) — long spot + short perp.

Vì sao: các chiến lược dự báo hướng đều âm sau phí. Carry là edge cơ học: thu
funding của perp, giữ spot làm hedge, không cần dự báo giá. Rủi ro chính là basis
(spot và perp lệch nhau) và phí vào/ra.

Dữ liệu: spot 1h + perp 1h từ data.binance.vision (cache ngoài git), funding thật
từ cache `data/funding`. Mỗi chu kỳ (tháng/quý) vào 1 lần, thoát cuối chu kỳ.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from . import funding as funding_mod

MONTHLY = {
    "spot": "https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{stamp}.zip",
    "perp": "https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{stamp}.zip",
}
DAY_MS = 86_400_000


def _months(start: date, end: date) -> list[str]:
    y, m = start.year, start.month
    out: list[str] = []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _parse_zip(payload: bytes) -> dict[int, float]:
    out: dict[int, float] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            if not name.endswith(".csv"):
                continue
            for row in csv.reader(io.StringIO(zf.read(name).decode("utf-8"))):
                if len(row) < 5:
                    continue
                try:
                    ts = int(float(row[0]))
                    close = float(row[4])
                except ValueError:
                    continue
                # Binance co file ghi micro-giay; chuan hoa ve mili-giay
                while ts > 10**13:
                    ts //= 1000
                if ts < 10**11:
                    ts *= 1000
                if not (10**12 <= ts <= 2 * 10**12) or close <= 0:
                    continue
                out[ts] = close
    return out


def load_hourly(kind: str, sym: str, start: date, end: date, cache_dir: Path) -> dict[int, float]:
    lo = int(calendar.timegm(start.timetuple())) * 1000
    hi = int(calendar.timegm(end.timetuple())) * 1000
    p = cache_dir / kind / f"{sym}.json"
    if p.is_file():
        raw = json.loads(p.read_text(encoding="utf-8"))
        cached = {
            int(k): float(v)
            for k, v in raw.items()
            if 10**12 <= int(k) <= 2 * 10**12 and float(v) > 0
        }
        if cached and min(cached) <= lo and max(cached) >= hi - 3_600_000:
            return {k: v for k, v in cached.items() if lo <= k < hi}
        # cache khong phu khoang yeu cau -> tai va gop
        out = dict(cached)
        from ..data.downloader import http_fetch

        for stamp in _months(start, end):
            url = MONTHLY[kind].format(sym=sym, stamp=stamp)
            try:
                out.update(_parse_zip(http_fetch(url, timeout=30)))
            except Exception:
                continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({str(k): v for k, v in sorted(out.items())}), encoding="utf-8")
        return {k: v for k, v in out.items() if lo <= k < hi}
    from ..data.downloader import http_fetch

    out: dict[int, float] = {}
    for stamp in _months(start, end):
        url = MONTHLY[kind].format(sym=sym, stamp=stamp)
        try:
            out.update(_parse_zip(http_fetch(url, timeout=30)))
        except Exception:
            continue
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({str(k): v for k, v in sorted(out.items())}), encoding="utf-8")
    return out


def month_bounds(ts: int) -> tuple[int, int]:
    d = date.fromtimestamp(ts / 1000)
    start = int(calendar.timegm(date(d.year, d.month, 1).timetuple())) * 1000
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    end = int(calendar.timegm(date(y, m, 1).timetuple())) * 1000
    return start, end


def month_cycles(spot: dict[int, float]) -> dict[str, tuple[int, int]]:
    """month_key -> (first_ts, last_ts) co du lieu."""
    buckets: dict[str, list[int]] = {}
    for ts in spot:
        d = date.fromtimestamp(ts / 1000)
        buckets.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(ts)
    return {k: (min(v), max(v)) for k, v in buckets.items()}


def cycle_return(
    spot: dict[int, float],
    perp: dict[int, float],
    funding: dict[int, float],
    first_ts: int,
    last_ts: int,
    *,
    fee_bps: float,
) -> float | None:
    """Return trên 1 notional cho 1 chu ky (long spot + short perp)."""
    s0, s1 = spot.get(first_ts), spot.get(last_ts)
    p0, p1 = perp.get(first_ts), perp.get(last_ts)
    if None in (s0, s1, p0, p1) or not p0:
        return None
    basis = (s1 / s0 - 1.0) - (p1 / p0 - 1.0)
    fund = sum(r for ts, r in funding.items() if first_ts <= ts <= last_ts)
    return fund + basis - fee_bps / 10_000


def stats(monthly: list[float], periods_per_year: int = 12) -> dict[str, Any]:
    if not monthly:
        return {"n": 0}
    eq = 1.0
    peak = 1.0
    dd = 0.0
    for r in monthly:
        eq *= 1.0 + r
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    mean = sum(monthly) / len(monthly)
    var = sum((x - mean) ** 2 for x in monthly) / max(1, len(monthly) - 1)
    vol = var**0.5
    years = len(monthly) / periods_per_year
    return {
        "n": len(monthly),
        "total_return_pct": round((eq - 1) * 100, 2),
        "cagr_pct": round(((eq ** (1 / years)) - 1) * 100, 2) if years > 0 and eq > 0 else -100.0,
        "vol_pct": round(vol * (periods_per_year**0.5) * 100, 2),
        "sharpe": round(mean / vol * (periods_per_year**0.5), 2) if vol > 0 else None,
        "max_dd_pct": round(dd * 100, 2),
        "worst_month_pct": round(min(monthly) * 100, 2),
        "hit_pct": round(sum(1 for x in monthly if x > 0) / len(monthly), 4),
    }


def run(
    data_dir: Path,
    symbols: list[str],
    start: date,
    end: date,
    *,
    fee_bps: float = 38.0,
    every_months: int = 1,
    min_funding: float = 0.0,
) -> dict[str, Any]:
    cache = data_dir / "carry"
    spot: dict[str, dict[int, float]] = {}
    perp: dict[str, dict[int, float]] = {}

    def _load(sym: str) -> tuple[str, dict[int, float], dict[int, float]]:
        return (
            sym,
            load_hourly("spot", sym, start, end, cache),
            load_hourly("perp", sym, start, end, cache),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, s, p in pool.map(_load, symbols):
            spot[sym], perp[sym] = s, p

    funding: dict[str, dict[int, float]] = {}
    for sym in symbols:
        rates, _ok = funding_mod.load_or_fetch(data_dir, sym, start, end)
        funding[sym] = rates

    # Chu ky: gop `every_months` thang lien tiep
    month_keys = sorted({k for s in spot.values() for k in month_cycles(s)})
    cycles: list[tuple[str, list[str]]] = []
    for i in range(0, len(month_keys), every_months):
        group = month_keys[i : i + every_months]
        cycles.append((group[0], group))

    per_symbol: dict[str, list[float]] = {s: [] for s in symbols}
    monthly: list[float] = []
    for _label, group in cycles:
        rets: list[float] = []
        for sym in symbols:
            cycles_map = month_cycles(spot[sym])
            if not cycles_map:
                continue
            first = cycles_map.get(group[0])
            last = cycles_map.get(group[-1])
            if not first or not last:
                continue
            r = cycle_return(spot[sym], perp[sym], funding[sym], first[0], last[1], fee_bps=fee_bps)
            if r is None:
                continue
            if min_funding > 0:
                fsum = sum(rate for ts, rate in funding[sym].items() if first[0] <= ts <= last[1])
                if fsum < min_funding:
                    continue
            rets.append(r)
            per_symbol[sym].append(r)
        if rets:
            monthly.append(sum(rets) / len(rets))
    st = stats(monthly, periods_per_year=12 // every_months)
    fund_apy: dict[str, float] = {}
    for sym in symbols:
        rates = funding[sym]
        if rates:
            years = max(1e-9, (max(rates) - min(rates)) / (365 * DAY_MS))
            fund_apy[sym] = round(sum(rates.values()) / years * 100, 2)
    return {
        "fee_bps_per_cycle": fee_bps,
        "every_months": every_months,
        "months_used": len(monthly),
        "portfolio": st,
        "funding_apy_pct": fund_apy,
        "per_symbol_mean_pct": {
            s: round(sum(v) / len(v) * 100, 3) for s, v in per_symbol.items() if v
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Funding carry delta-neutral (spot + perp)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,SUIUSDT",
    )
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/reports/p1.4c-carry.json")
    args = ap.parse_args(argv)
    t0 = time.time()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    data_dir = Path(args.data_dir)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    out = {"period": {"start": args.start, "end": args.end}, "runs": {}}
    for fee in (38.0, 20.0):
        for every in (1, 3):
            for min_f in (0.0, 0.001, 0.002):
                key = f"fee{fee:g}_every{every}m_min{min_f:g}"
                out["runs"][key] = run(
                    data_dir,
                    symbols,
                    start,
                    end,
                    fee_bps=fee,
                    every_months=every,
                    min_funding=min_f,
                )
                st = out["runs"][key]["portfolio"]
                print(
                    f"{key:32s} thang={out['runs'][key]['months_used']:3d} "
                    f"CAGR={st.get('cagr_pct')}% vol={st.get('vol_pct')}% "
                    f"Sharpe={st.get('sharpe')} DD={st.get('max_dd_pct')}%",
                    flush=True,
                )
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
