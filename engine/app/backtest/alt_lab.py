"""Phòng thử altcoin-only (P1.4f): mục tiêu 5-10%/tháng, lỗ tháng <= 5-10%.

BTC chỉ làm tham chiếu, KHÔNG trade. Universe: altcoin có dữ liệu 1h perp.

Các họ thử:
  - trend_long   : long alt khi close > SMA(n), giữ đến khi dưới SMA
  - mom_top      : mỗi tuần long top-N alt theo return lookback
  - donchian     : breakout 20 ngày / exit 10 ngày, long-only
  - funding_dip  : long khi funding 24h annualized < -ngưỡng, giữ H ngày

Tất cả báo theo THÁNG: mean/median/best/worst, % tháng >=5%, % tháng <=-10%.
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
from . import portfolio_lab as pl
from . import wide_lab as wl

DAY_MS = 86_400_000


def monthly_stats(curve: list[float], days: list[int]) -> dict[str, Any]:
    """curve[i] = equity sau ngày days[i] (bat dau tu 1.0)."""
    if not curve:
        return {"n_months": 0}
    by_month: dict[str, list[float]] = defaultdict(list)
    for i, d in enumerate(days[: len(curve)]):
        key = date.fromtimestamp(d / 1000).strftime("%Y-%m")
        by_month[key].append(curve[i])
    rets: list[float] = []
    prev_close = 1.0
    for _k, vals in sorted(by_month.items()):
        end = vals[-1]
        rets.append(end / prev_close - 1.0)
        prev_close = end
    if not rets:
        return {"n_months": 0}
    mean = sum(rets) / len(rets)
    return {
        "n_months": len(rets),
        "mean_pct": round(mean * 100, 2),
        "median_pct": round(sorted(rets)[len(rets) // 2] * 100, 2),
        "best_pct": round(max(rets) * 100, 2),
        "worst_pct": round(min(rets) * 100, 2),
        "pct_months_ge5": round(sum(1 for r in rets if r >= 0.05) / len(rets), 3),
        "pct_months_le_neg10": round(sum(1 for r in rets if r <= -0.10) / len(rets), 3),
        "pct_months_positive": round(sum(1 for r in rets if r > 0) / len(rets), 3),
        "monthly": [round(r * 100, 2) for r in rets],
    }


def _curve(sim: dict[str, Any]) -> list[float]:
    return sim.get("curve", [])


def funding_dip_weights(
    closes: dict[str, dict[int, float]],
    fund: dict[str, dict[int, float]],
    days: list[int],
    *,
    threshold: float,
    hold: int,
    max_pos: int,
    gross: float,
) -> dict[str, list[float]]:
    syms = sorted(closes)
    n = len(days)
    w = {s: [0.0] * n for s in syms}
    idx = {d: i for i, d in enumerate(days)}
    for sym in syms:
        px = closes[sym]
        fund_s = fund.get(sym, {})
        busy_until = -1
        for i, d in enumerate(days):
            if i <= busy_until or d not in px or d not in fund_s:
                continue
            if wl._ann(fund_s[d]) >= -threshold:
                continue
            exit_i = min(i + hold, n - 1)
            for k in range(i + 1, exit_i + 1):
                w[sym][k] = gross / max_pos
            busy_until = exit_i
            _ = idx
    # chuan hoa de tong gross <= gross moi ngay
    for i in range(n):
        tot = sum(abs(w[s][i]) for s in syms)
        if tot > gross:
            for s in syms:
                w[s][i] *= gross / tot
    return w


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Altcoin-only lab (bỏ BTC)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument(
        "--symbols",
        default=(
            "ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,"
            "TRXUSDT,APTUSDT,NEARUSDT,ATOMUSDT,FILUSDT,LTCUSDT,DOTUSDT,UNIUSDT,"
            "AAVEUSDT,ETCUSDT,ARBUSDT,OPUSDT,SUIUSDT,TONUSDT,INJUSDT"
        ),
    )
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-11-01")
    ap.add_argument("--out", default="data/reports/p1.4f-alt.json")
    args = ap.parse_args(argv)

    t0 = time.time()
    data_dir = Path(args.data_dir)
    cache = data_dir / "carry"
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    from concurrent.futures import ThreadPoolExecutor

    def _one(sym: str):
        return sym, carry_lab.load_hourly("perp", sym, start, end, cache)

    closes: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, perp in pool.map(_one, symbols):
            if perp and sym != "BTCUSDT":
                closes[sym] = wl.daily_closes(perp)

    def _fund(sym: str):
        rates, _ok = carry_lab.funding_mod.load_or_fetch(data_dir, sym, start, end)
        return sym, wl.funding_days(rates)

    fund: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, fdays in pool.map(_fund, sorted(closes)):
            fund[sym] = fdays

    # chỉ giữ symbol có mặt ở >=80% số ngày
    all_days = sorted({d for px in closes.values() for d in px})
    need = int(0.8 * len(all_days))
    closes = {s: px for s, px in closes.items() if len(px) >= need}
    days = sorted(set.intersection(*(set(px) for px in closes.values()))) if closes else []
    print(f"alt symbols={len(closes)} ngay chung={len(days)}", flush=True)
    if len(days) < 200:
        print("khong du du lieu chung")
        return 2

    px_list = {s: [closes[s][d] for d in days] for s in closes}
    rets = pl.returns_by_day(px_list)
    n_sym = len(px_list)
    out: dict[str, Any] = {
        "period": {"start": args.start, "end": args.end},
        "symbols": sorted(closes),
        "days": len(days),
        "strategies": {},
    }

    def add(name: str, sim: dict[str, Any], gross: float) -> None:
        st = monthly_stats(_curve(sim), days)
        st.update(
            {
                "gross": gross,
                "cagr_pct": sim.get("cagr_pct"),
                "max_dd_pct": sim.get("max_dd_pct"),
                "sharpe": sim.get("sharpe"),
                "cost_drag_pct": sim.get("cost_drag_pct"),
            }
        )
        out["strategies"][name] = st
        print(
            f"{name:28s} gross={gross:g} mean/th={st.get('mean_pct')}% "
            f"median={st.get('median_pct')}% worst={st.get('worst_pct')}% "
            f">=5%: {st.get('pct_months_ge5')} CAGR={st.get('cagr_pct')}% "
            f"DD={st.get('max_dd_pct')}%",
            flush=True,
        )

    for gross in (1.0, 2.0, 3.0):
        # 1) trend long: close > SMA100
        for sma_n in (50, 100):
            w = {}
            for s in px_list:
                sma = pl._sma(px_list[s], sma_n)
                w[s] = [
                    gross / n_sym if sma[i] is not None and px_list[s][i] > sma[i] else 0.0
                    for i in range(len(days))
                ]
            sim = pl.simulate(w, rets, fund, days, cost_bps=10)
            add(f"trend_sma{sma_n}", sim, gross)

        # 2) momentum top-5, rebalance 7 ngày
        for lb in (14, 30):
            w = pl.xs_weights(px_list, lookback=lb, hold=7, top_n=5, gross=gross)
            # long-only: bỏ chân short để so sánh (alt short đắt)
            w_long = {s: [max(0.0, x) for x in w[s]] for s in w}
            sim = pl.simulate(w_long, rets, fund, days, cost_bps=10)
            add(f"mom{lb}_top5", sim, gross)

        # 3) donchian long-only
        wd = pl.donchian_weights(
            {
                s: [
                    {
                        "day": d,
                        "h": px_list[s][i] * 1.001,
                        "l": px_list[s][i] * 0.999,
                        "c": px_list[s][i],
                    }
                    for i, d in enumerate(days)
                ]
                for s in px_list
            },
            days,
            entry_n=20,
            exit_n=10,
            gross=gross,
        )
        wd = {s: [max(0.0, x) for x in wd[s]] for s in wd}
        sim = pl.simulate(wd, rets, fund, days, cost_bps=10)
        add("donchian20_10", sim, gross)

        # 4) funding dip
        for thr, hold in ((0.30, 3), (0.20, 7)):
            wf = funding_dip_weights(
                closes, fund, days, threshold=thr, hold=hold, max_pos=5, gross=gross
            )
            sim = pl.simulate(wf, rets, fund, days, cost_bps=10)
            add(f"funding_dip_thr{thr:g}_h{hold}", sim, gross)

    # benchmark BTC (chỉ tham chiếu)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
