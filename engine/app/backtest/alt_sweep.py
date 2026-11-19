"""Sweep P1.4g: cố đạt 5-10%/tháng trên altcoin (bỏ BTC).

Không thêm tín hiệu mới; chỉ thử các biến thể vận hành của funding-dip và trend:
  - nhiều vị thế hơn (max_pos 5/10), giữ ngắn (1/3 ngày)
  - vol targeting: giảm size khi vol cao, tăng khi vol thấp (cap 0.5x-2x)
  - universe tập trung (8 alt biến động cao)
Báo cáo theo tháng + audit dấu hiệu bất thường nếu mean > 10%/tháng.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from . import alt_lab as alt
from . import carry_lab
from . import portfolio_lab as pl
from . import wide_lab as wl

DAY_MS = 86_400_000
HIGH_VOL = (
    "DOGEUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "INJUSDT",
    "SUIUSDT",
    "APTUSDT",
    "NEARUSDT",
    "LINKUSDT",
)


def vol_target_weights(
    w: dict[str, list[float]],
    px_list: dict[str, list[float]],
    *,
    target_daily_vol: float = 0.03,
    lookback: int = 14,
    cap: tuple[float, float] = (0.5, 2.0),
) -> dict[str, list[float]]:
    """Scale từng symbol theo target/realized vol, cap để tránh bùng nổ."""
    out: dict[str, list[float]] = {}
    for s, series in w.items():
        px = px_list[s]
        rets = [0.0] + [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]
        scaled: list[float] = []
        for i, wt in enumerate(series):
            if wt == 0 or i < lookback:
                scaled.append(wt)
                continue
            window = rets[i - lookback + 1 : i + 1]
            sd = (sum((x - sum(window) / len(window)) ** 2 for x in window) / len(window)) ** 0.5
            if sd <= 0:
                scaled.append(wt)
                continue
            scale = min(cap[1], max(cap[0], target_daily_vol / sd))
            scaled.append(wt * scale)
        out[s] = scaled
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Alt sweep P1.4g")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-11-01")
    ap.add_argument("--out", default="data/reports/p1.4g-alt-sweep.json")
    args = ap.parse_args(argv)

    t0 = time.time()
    data_dir = Path(args.data_dir)
    cache = data_dir / "carry"
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    symbols = [
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "TRXUSDT",
        "APTUSDT",
        "NEARUSDT",
        "ATOMUSDT",
        "FILUSDT",
        "LTCUSDT",
        "DOTUSDT",
        "UNIUSDT",
        "AAVEUSDT",
        "ETCUSDT",
        "ARBUSDT",
        "OPUSDT",
        "SUIUSDT",
        "TONUSDT",
        "INJUSDT",
    ]
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

    all_days = sorted({d for px in closes.values() for d in px})
    need = int(0.8 * len(all_days))
    closes = {s: px for s, px in closes.items() if len(px) >= need}
    days = sorted(set.intersection(*(set(px) for px in closes.values())))
    px_list = {s: [closes[s][d] for d in days] for s in closes}
    rets = pl.returns_by_day(px_list)
    out: dict[str, Any] = {
        "period": {"start": args.start, "end": args.end},
        "days": len(days),
        "symbols": sorted(closes),
        "runs": {},
    }
    print(f"alt={len(closes)} ngay={len(days)}", flush=True)

    def add(name: str, w: dict[str, list[float]], *, cost_bps: float = 10.0) -> None:
        sim = pl.simulate(w, rets, fund, days, cost_bps=cost_bps)
        st = alt.monthly_stats(sim.get("curve", []), days)
        st.update(
            {
                "cagr_pct": sim.get("cagr_pct"),
                "max_dd_pct": sim.get("max_dd_pct"),
                "sharpe": sim.get("sharpe"),
                "cost_drag_pct": sim.get("cost_drag_pct"),
            }
        )
        out["runs"][name] = st
        print(
            f"{name:34s} mean/th={st.get('mean_pct')}% med={st.get('median_pct')}% "
            f"worst={st.get('worst_pct')}% >=5%={st.get('pct_months_ge5')} "
            f"CAGR={st.get('cagr_pct')}% DD={st.get('max_dd_pct')}%",
            flush=True,
        )

    # 1) funding-dip sweep
    for max_pos in (5, 10):
        for hold in (1, 3):
            for gross in (2.0, 3.0, 4.0):
                w = alt.funding_dip_weights(
                    closes, fund, days, threshold=0.30, hold=hold, max_pos=max_pos, gross=gross
                )
                add(f"fd_h{hold}_mp{max_pos}_g{gross:g}", w)

    # 2) funding-dip + vol targeting
    for gross in (2.0, 3.0, 4.0):
        w = alt.funding_dip_weights(
            closes, fund, days, threshold=0.30, hold=3, max_pos=5, gross=gross
        )
        add(f"fd_voltgt_g{gross:g}", vol_target_weights(w, px_list))

    # 3) trend + vol targeting
    n_sym = len(px_list)
    for gross in (2.0, 3.0):
        w = {}
        for s in px_list:
            sma = pl._sma(px_list[s], 100)
            w[s] = [
                gross / n_sym if sma[i] is not None and px_list[s][i] > sma[i] else 0.0
                for i in range(len(days))
            ]
        add(f"trend100_voltgt_g{gross:g}", vol_target_weights(w, px_list))

    # 4) universe tập trung (8 alt biến động cao)
    hv = {s: closes[s] for s in HIGH_VOL if s in closes}
    if len(hv) >= 5:
        hv_days = sorted(set.intersection(*(set(p) for p in hv.values())))
        hv_px = {s: [hv[s][d] for d in hv_days] for s in hv}
        hv_rets = pl.returns_by_day(hv_px)
        hv_fund = {s: fund[s] for s in hv}
        for gross in (2.0, 3.0):
            w = alt.funding_dip_weights(
                hv, hv_fund, hv_days, threshold=0.30, hold=3, max_pos=5, gross=gross
            )
            sim = pl.simulate(w, hv_rets, hv_fund, hv_days, cost_bps=10)
            st = alt.monthly_stats(sim.get("curve", []), hv_days)
            st.update({"cagr_pct": sim.get("cagr_pct"), "max_dd_pct": sim.get("max_dd_pct")})
            out["runs"][f"fd_highvol_g{gross:g}"] = st
            print(
                f"{'fd_highvol_g' + str(gross):34s} mean/th={st.get('mean_pct')}% "
                f"worst={st.get('worst_pct')}% CAGR={st.get('cagr_pct')}% "
                f"DD={st.get('max_dd_pct')}%",
                flush=True,
            )

    # audit: đếm run mean > 10%/tháng
    hot = {k: v for k, v in out["runs"].items() if (v.get("mean_pct") or 0) > 10}
    out["audit_flags"] = sorted(hot)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"run mean>10%/thang: {out['audit_flags']}")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
