"""Kiểm tra kỹ ứng viên "funding capitulation long" (P1.4d).

Tín hiệu: funding 24h annualized < -ngưỡng (phe short đang trả tiền, crowded short)
-> long perp, giữ H ngày. Đây là ứng viên duy nhất dương trong P1.4d, nên phải
stress-test: theo năm, theo symbol, theo ngưỡng/hold, và so với benchmark beta.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from . import carry_lab
from . import wide_lab as wl

DAY_MS = 86_400_000


def adverse_risk(
    trades: list[dict[str, Any]],
    closes: dict[str, dict[int, float]],
    *,
    leverage: float,
    mmr: float = 0.005,
) -> dict[str, Any]:
    """Uoc luong rui ro thanh ly: so lan adverse 1 ngay x leverage >= 1/L - MMR."""
    thresh = 1.0 / max(1.0, leverage) - mmr
    worst = 0.0
    breach = 0
    for t in trades:
        px = closes.get(t["symbol"], {})
        keys = sorted(k for k in px if t["entry_day"] <= k <= t["entry_day"] + t["days"] * DAY_MS)
        if len(keys) < 2:
            continue
        side = t["side"]
        for a, b in zip(keys, keys[1:]):
            move = (px[b] / px[a] - 1.0) * side
            adverse = -move
            worst = max(worst, adverse)
            if adverse >= thresh:
                breach += 1
    return {
        "leverage": leverage,
        "liq_threshold_pct": round(thresh * 100, 1),
        "worst_adverse_day_pct": round(worst * 100, 2),
        "liq_breach_days": breach,
    }


def by_year(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        y = date.fromtimestamp(t["entry_day"] / 1000).year
        buckets[str(y)].append(t["net"])
    return {
        y: {
            "n": len(v),
            "mean_bps": round(sum(v) / len(v) * 10_000, 1),
            "hit_pct": round(sum(1 for x in v if x > 0) / len(v), 3),
        }
        for y, v in sorted(buckets.items())
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stress-test funding capitulation long")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument(
        "--symbols",
        default=(
            "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,"
            "LINKUSDT,SUIUSDT,TRXUSDT,TONUSDT,APTUSDT,ARBUSDT,OPUSDT,NEARUSDT,"
            "ATOMUSDT,FILUSDT,INJUSDT,LTCUSDT,DOTUSDT,UNIUSDT,AAVEUSDT,ETCUSDT"
        ),
    )
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-11-01")
    ap.add_argument("--out", default="data/reports/p1.4d-funding-long.json")
    args = ap.parse_args(argv)

    t0 = time.time()
    data_dir = Path(args.data_dir)
    cache = data_dir / "carry"
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    from concurrent.futures import ThreadPoolExecutor

    def _one(sym: str):
        return sym, carry_lab.load_hourly("perp", sym, start, end, cache)

    closes: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, perp in pool.map(_one, symbols):
            if perp:
                closes[sym] = wl.daily_closes(perp)

    def _fund(sym: str):
        rates, _ok = carry_lab.funding_mod.load_or_fetch(data_dir, sym, start, end)
        return sym, wl.funding_days(rates)

    fund: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, fdays in pool.map(_fund, sorted(closes)):
            fund[sym] = fdays
    days = sorted({d for px in closes.values() for d in px})
    print(f"symbol={len(closes)} ngay={len(days)}", flush=True)

    out: dict[str, Any] = {"period": {"start": args.start, "end": args.end}, "runs": {}}
    for thr in (0.20, 0.30, 0.50):
        for hold in (1, 3, 7):
            trades = wl.funding_extreme_trades(
                closes, fund, days, threshold_ann=thr, hold=hold, mode="long"
            )
            st = wl.trade_stats(trades)
            curves = {
                f"lev{lv:g}": wl.portfolio_curve(trades, days, leverage=lv) for lv in (1, 2, 3, 5)
            }
            key = f"long_thr{thr:g}_h{hold}"
            out["runs"][key] = {
                "stats": st,
                "curves": curves,
                "by_year": by_year(trades),
                "liq": {f"lev{lv:g}": adverse_risk(trades, closes, leverage=lv) for lv in (3, 5)},
            }
            print(
                f"{key:18s} n={st.get('n', 0):4d} mean={st.get('mean_bps')}bps "
                f"t={st.get('t_stat')} coin+={st.get('symbols_positive_pct')} "
                f"| 1x CAGR={curves['lev1']['cagr_pct']}% DD={curves['lev1']['max_dd_pct']}% "
                f"| 3x {curves['lev3']['cagr_pct']}%/{curves['lev3']['max_dd_pct']}% "
                f"| 5x {curves['lev5']['cagr_pct']}%/{curves['lev5']['max_dd_pct']}%",
                flush=True,
            )

    # Benchmark beta tren cung khoang
    if "BTCUSDT" in closes:
        btc_days = sorted(closes["BTCUSDT"])
        btc_px = [closes["BTCUSDT"][d] for d in btc_days]
        for name, kwargs in (
            ("btc_buy_hold", {"sma_n": 1, "leverage": 1.0}),
            ("btc_sma200", {"sma_n": 200, "leverage": 1.0}),
            ("btc_sma200_2x", {"sma_n": 200, "leverage": 2.0}),
            ("btc_sma200_3x", {"sma_n": 200, "leverage": 3.0}),
            ("btc_sma200_4x", {"sma_n": 200, "leverage": 4.0}),
            ("btc_sma200_5x", {"sma_n": 200, "leverage": 5.0}),
        ):
            st = wl.sma_filter_curve(btc_px, btc_days, **kwargs)
            out["runs"][name] = st
            print(
                f"{name:18s} CAGR={st.get('cagr_pct')}% Sharpe={st.get('sharpe')} "
                f"DD={st.get('max_dd_pct')}% worst_day={st.get('worst_day_pct')}% "
                f"liq_days={st.get('liq_days')} 300USD->{st.get('usd_end_300')}",
                flush=True,
            )

    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
