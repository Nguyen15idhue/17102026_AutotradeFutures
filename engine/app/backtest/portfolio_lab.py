"""Phòng thử chiến lược danh mục (P1.4c) — tìm nguồn lợi nhuận khác ngoài tín hiệu 15m.

Vì sao cần: quét tín hiệu 15m–4h cho thấy edge nhỏ hơn chi phí. Các họ chiến lược
còn lại có cơ chế khác hẳn và đều kiểm được bằng dữ liệu đang có:

  - xsmom  : momentum tương đối (long coin mạnh, short coin yếu)
  - xsrev  : đảo chiều ngắn hạn tương đối (long coin yếu)
  - tsmom  : trend following theo thời gian (long/short theo SMA/Donchian)
  - funding: carry funding trên perp (short coin funding cao, long funding thấp)

Mô phỏng theo ngày (close-to-close), trọng số bằng nhau, có phí theo turnover và
funding thật. Không dùng đòn bẩy quá 1.0 gross — đây là nghiên cứu edge, không phải
tối ưu đòn bẩy.
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any

from .. import config as config_mod
from ..data import parquet_io
from . import funding as funding_mod

DAY_MS = 86_400_000
MIN_BARS_PER_DAY = 1000  # ngày thiếu > ~40% nến thì bỏ


def load_daily(root: str | Path, symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Gom 1m parquet thành nến ngày UTC."""
    root = Path(root)
    buckets: dict[int, dict[str, Any]] = {}
    for day in parquet_io.list_days(root, symbol, "1m"):
        rows = parquet_io.load_day(root, symbol, "1m", day)
        for r in rows:
            ts = int(r["open_time"])
            if ts < start_ms or ts >= end_ms:
                continue
            d = ts // DAY_MS * DAY_MS
            rec = buckets.setdefault(
                d,
                {
                    "day": d,
                    "o": float(r["o"]),
                    "h": float(r["h"]),
                    "l": float(r["l"]),
                    "c": float(r["c"]),
                    "v": 0.0,
                    "n": 0,
                },
            )
            rec["h"] = max(rec["h"], float(r["h"]))
            rec["l"] = min(rec["l"], float(r["l"]))
            rec["c"] = float(r["c"])
            rec["v"] += float(r.get("v") or 0.0)
            rec["n"] += 1
    return [buckets[d] for d in sorted(buckets) if buckets[d]["n"] >= MIN_BARS_PER_DAY]


def funding_by_day(rates: dict[int, float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for ts, rate in rates.items():
        d = int(ts) // DAY_MS * DAY_MS
        out[d] = out.get(d, 0.0) + float(rate)
    return out


def _sma(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    run = 0.0
    for i, x in enumerate(xs):
        run += x
        if i >= n:
            run -= xs[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def _common_days(daily: dict[str, list[dict[str, Any]]]) -> list[int]:
    sets = [set(int(b["day"]) for b in bars) for bars in daily.values() if bars]
    if not sets:
        return []
    common = sets[0]
    for s in sets[1:]:
        common &= s
    return sorted(common)


def _closes_on(daily: dict[str, list[dict[str, Any]]], days: list[int]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for sym, bars in daily.items():
        by_day = {int(b["day"]): float(b["c"]) for b in bars}
        if all(d in by_day for d in days):
            out[sym] = [by_day[d] for d in days]
    return out


# ---------- trọng số các chiến lược ----------


def xs_weights(
    closes: dict[str, list[float]],
    *,
    lookback: int,
    hold: int,
    top_n: int,
    gross: float = 1.0,
    reverse: bool = False,
) -> dict[str, list[float]]:
    """Long top_n coin mạnh nhất (hoặc yếu nhất nếu reverse), short nhóm đối diện."""
    syms = sorted(closes)
    n = len(closes[syms[0]]) if syms else 0
    w = {s: [0.0] * n for s in syms}
    if n == 0:
        return w
    leg = gross / 2.0 / max(1, top_n)
    cur = {s: 0.0 for s in syms}
    for t in range(n):
        if t >= lookback and (t - lookback) % hold == 0:
            scores = {s: closes[s][t] / closes[s][t - lookback] - 1.0 for s in syms}
            ranked = sorted(syms, key=lambda s: scores[s], reverse=not reverse)
            longs, shorts = ranked[:top_n], ranked[-top_n:]
            cur = {s: 0.0 for s in syms}
            for s in longs:
                cur[s] = leg
            for s in shorts:
                cur[s] = -leg
        for s in syms:
            w[s][t] = cur[s]
    return w


def tsmom_weights(
    closes: dict[str, list[float]], *, fast: int, slow: int, gross: float = 1.0
) -> dict[str, list[float]]:
    """Long khi SMA(fast) > SMA(slow), short khi ngược; trọng số bằng nhau."""
    syms = sorted(closes)
    n = len(closes[syms[0]]) if syms else 0
    per = gross / max(1, len(syms))
    out: dict[str, list[float]] = {}
    for s in syms:
        f, sl = _sma(closes[s], fast), _sma(closes[s], slow)
        out[s] = [
            (per if f[i] > sl[i] else -per) if f[i] is not None and sl[i] is not None else 0.0
            for i in range(n)
        ]
    return out


def donchian_weights(
    daily: dict[str, list[dict[str, Any]]],
    days: list[int],
    *,
    entry_n: int = 20,
    exit_n: int = 10,
    gross: float = 1.0,
) -> dict[str, list[float]]:
    """Breakout Donchian: vào khi phá đỉnh entry_n ngày, thoát khi thủng đáy exit_n ngày."""
    syms = sorted(daily)
    per = gross / max(1, len(syms))
    out: dict[str, list[float]] = {}
    for s in syms:
        by_day = {int(b["day"]): b for b in daily[s]}
        highs = [float(by_day[d]["h"]) if d in by_day else math.nan for d in days]
        lows = [float(by_day[d]["l"]) if d in by_day else math.nan for d in days]
        closes = [float(by_day[d]["c"]) if d in by_day else math.nan for d in days]
        state = 0
        series: list[float] = []
        for i in range(len(days)):
            if i >= entry_n and i >= exit_n and not math.isnan(closes[i]):
                hi = max(highs[i - entry_n : i])
                lo = min(lows[i - entry_n : i])
                dlo = min(lows[i - exit_n : i])
                dhi = max(highs[i - exit_n : i])
                if state <= 0 and closes[i] > hi:
                    state = 1
                elif state >= 0 and closes[i] < lo:
                    state = -1
                elif state == 1 and closes[i] < dlo:
                    state = 0
                elif state == -1 and closes[i] > dhi:
                    state = 0
            series.append(state * per)
        out[s] = series
    return out


def funding_weights(
    fund_daily: dict[str, dict[int, float]],
    days: list[int],
    *,
    lookback: int = 3,
    top_n: int = 3,
    gross: float = 1.0,
    hedge_symbol: str | None = None,
) -> dict[str, list[float]]:
    """Short nhóm funding cao nhất, long nhóm thấp nhất (hoặc hedge bằng BTC)."""
    syms = sorted(fund_daily)
    n = len(days)
    w = {s: [0.0] * n for s in syms}
    leg = gross / 2.0 / max(1, top_n)
    cur = {s: 0.0 for s in syms}
    for t in range(n):
        if t >= lookback:
            scores = {}
            for s in syms:
                vals = [fund_daily[s].get(days[k], 0.0) for k in range(t - lookback, t)]
                scores[s] = sum(vals) / len(vals)
            ranked = sorted(syms, key=lambda s: scores[s], reverse=True)
            cur = {s: 0.0 for s in syms}
            for s in ranked[:top_n]:
                cur[s] = -leg
            if hedge_symbol:
                cur[hedge_symbol] = cur.get(hedge_symbol, 0.0) + leg * top_n
            else:
                for s in ranked[-top_n:]:
                    cur[s] = leg
        for s in syms:
            w[s][t] = cur[s]
    return w


# ---------- mô phỏng ----------


def returns_by_day(closes: dict[str, list[float]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for s, px in closes.items():
        out[s] = [0.0] + [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]
    return out


def simulate(
    weights: dict[str, list[float]],
    rets: dict[str, list[float]],
    fund_daily: dict[str, dict[int, float]],
    days: list[int],
    *,
    cost_bps: float = 10.0,
    periods_per_year: int = 365,
) -> dict[str, Any]:
    n = len(days)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    curve: list[float] = []
    daily: list[float] = []
    prev: dict[str, float] = {}
    turnover_sum = 0.0
    cost_sum = 0.0
    fund_sum = 0.0
    for t in range(n - 1):
        gross = sum(abs(weights[s][t]) for s in weights)
        pnl = sum(weights[s][t] * rets[s][t + 1] for s in weights)
        fund = sum(weights[s][t] * fund_daily.get(s, {}).get(days[t + 1], 0.0) for s in weights)
        turn = sum(abs(weights[s][t] - prev.get(s, 0.0)) for s in weights)
        cost = turn * cost_bps / 10_000
        net = pnl - fund - cost
        equity *= 1.0 + net
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append(equity)
        daily.append(net)
        turnover_sum += turn
        cost_sum += cost
        fund_sum += fund
        prev = {s: weights[s][t] for s in weights}
        _ = gross
    if not daily:
        return {"n_days": 0}
    mean = sum(daily) / len(daily)
    var = sum((x - mean) ** 2 for x in daily) / max(1, len(daily) - 1)
    vol = var**0.5
    years = len(daily) / periods_per_year
    cagr = equity ** (1 / years) - 1 if years > 0 and equity > 0 else -1.0
    return {
        "n_days": len(daily),
        "total_return_pct": round((equity - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * math.sqrt(periods_per_year) * 100, 2),
        "sharpe": round(mean / vol * math.sqrt(periods_per_year), 2) if vol > 0 else None,
        "max_dd_pct": round(max_dd * 100, 2),
        "hit_pct": round(sum(1 for x in daily if x > 0) / len(daily), 4),
        "cost_drag_pct": round(cost_sum * 100, 2),
        "funding_pnl_pct": round(-fund_sum * 100, 2),
        "turnover_per_day": round(turnover_sum / len(daily), 3),
        "equity_end": round(equity, 4),
        "curve_tail": [round(x, 4) for x in curve[-3:]],
    }


# ---------- CLI ----------


def _ms(d: date) -> int:
    return int(calendar.timegm(d.timetuple())) * 1000


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phòng thử chiến lược danh mục P1.4c")
    ap.add_argument("--config", default="config/mvp.mock.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/reports/p1.4c-portfolio.json")
    ap.add_argument("--cost-bps", type=float, default=10.0)
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        str(s) for s in cfg.universe.get("symbols", [])
    ]
    start_ms, end_ms = _ms(date.fromisoformat(args.start)), _ms(date.fromisoformat(args.end))
    root = Path(args.data_dir) / "market"
    t0 = time.time()

    daily: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols:
        bars = load_daily(root, sym, start_ms, end_ms)
        if bars:
            daily[sym] = bars
        print(f"daily {sym}: {len(bars)} ngay", flush=True)
    days = _common_days(daily)
    closes = _closes_on(daily, days)
    daily = {s: daily[s] for s in closes}
    rets = returns_by_day(closes)
    fund_raw: dict[str, dict[int, float]] = {}
    for sym in closes:
        rates, _ok = funding_mod.load_or_fetch(
            Path(args.data_dir), sym, date.fromisoformat(args.start), date.fromisoformat(args.end)
        )
        fund_raw[sym] = funding_by_day(rates)
    print(f"ngay chung: {len(days)} | symbol: {len(closes)}", flush=True)

    configs: dict[str, tuple[dict[str, list[float]], dict[str, dict[int, float]]]] = {}
    configs["xsmom7"] = (xs_weights(closes, lookback=7, hold=7, top_n=3), fund_raw)
    configs["xsmom30"] = (xs_weights(closes, lookback=30, hold=7, top_n=3), fund_raw)
    configs["xsrev3"] = (xs_weights(closes, lookback=3, hold=3, top_n=3, reverse=True), fund_raw)
    configs["tsmom50_200"] = (tsmom_weights(closes, fast=50, slow=200), fund_raw)
    configs["donchian20_10"] = (donchian_weights(daily, days, entry_n=20, exit_n=10), fund_raw)
    configs["funding_carry"] = (funding_weights(fund_raw, days, lookback=3, top_n=3), fund_raw)
    configs["funding_hedged"] = (
        funding_weights(fund_raw, days, lookback=3, top_n=3, hedge_symbol="BTCUSDT"),
        fund_raw,
    )

    out: dict[str, Any] = {
        "period": {"start": args.start, "end": args.end},
        "days": len(days),
        "symbols": sorted(closes),
        "cost_bps": args.cost_bps,
        "strategies": {},
    }
    print(
        f"{'chien luoc':18s} {'CAGR%':>7s} {'vol%':>7s} {'Sharpe':>7s} "
        f"{'MaxDD%':>7s} {'hit%':>6s} {'phi%':>7s} {'fund%':>7s}"
    )
    for name, (w, fr) in configs.items():
        st = simulate(w, rets, fr, days, cost_bps=args.cost_bps)
        out["strategies"][name] = st
        print(
            f"{name:18s} {st.get('cagr_pct', 0):7.2f} {st.get('vol_pct', 0):7.2f} "
            f"{st.get('sharpe') or 0:7.2f} {st.get('max_dd_pct', 0):7.2f} "
            f"{st.get('hit_pct', 0) * 100:6.1f} {st.get('cost_drag_pct', 0):7.2f} "
            f"{st.get('funding_pnl_pct', 0):7.2f}"
        )
    out["elapsed_s"] = round(time.time() - t0, 1)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {out['elapsed_s']}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
