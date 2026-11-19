"""Phòng thử P1.4d — phương án rủi ro cao hơn cho vốn nhỏ (300 USD).

Ý tưởng: nếu edge nằm ở chỗ khác OHLCV, một ứng viên có cơ chế rõ là **funding cực trị**
(crowded positioning). Khi funding bị đẩy rất cao, phe long đang trả giá để giữ vị thế；
short perp vừa nhận funding vừa có xác suất điều chỉnh. Ngược lại funding âm sâu → long.

Mô phỏng: tín hiệu tại close ngày t, vào/ra tại close, giữ tối đa H ngày, tối đa 5 vị thế
đồng thời (mỗi vị thế 1/5 gross), phí 10 bps mỗi chiều, funding thật.

Cũng chạy xsmom trên universe rộng để so sánh (cùng khung ngày).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from . import carry_lab
from . import portfolio_lab as pl

DAY_MS = 86_400_000
MAX_POS = 5


def daily_closes(hourly: dict[int, float]) -> dict[int, float]:
    """Giá close cuối cùng của mỗi ngày UTC."""
    out: dict[int, float] = {}
    for ts, px in sorted(hourly.items()):
        d = ts // DAY_MS * DAY_MS
        out[d] = px
    return out


def funding_days(rates: dict[int, float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for ts, r in rates.items():
        d = ts // DAY_MS * DAY_MS
        out[d] = out.get(d, 0.0) + r
    return out


def _ann(funding_day: float) -> float:
    return funding_day * 365.0


def funding_extreme_trades(
    closes: dict[str, dict[int, float]],
    funding: dict[str, dict[int, float]],
    days: list[int],
    *,
    threshold_ann: float,
    hold: int,
    mode: str = "short",
    cost_bps: float = 20.0,
) -> list[dict[str, Any]]:
    """Danh sach trade (mot phan tu = 1 lan vao lenh), khong chong lan trong 1 symbol."""
    trades: list[dict[str, Any]] = []
    for sym, px in closes.items():
        fund = funding.get(sym, {})
        busy_until = -1
        for i, d in enumerate(days):
            if i <= busy_until or d not in px:
                continue
            f = fund.get(d)
            if f is None:
                continue
            ann = _ann(f)
            side = 1 if (mode == "short" and ann > threshold_ann) else -1
            if mode == "long":
                side = 1 if ann < -threshold_ann else 0
            else:
                side = -1 if ann > threshold_ann else 0
            if side == 0:
                continue
            entry_i = i
            exit_i = min(i + hold, len(days) - 1)
            entry = px[d]
            exit_px = px.get(days[exit_i])
            if exit_px is None:
                continue
            ret = (exit_px / entry - 1.0) * side
            fund_sum = sum(fund.get(days[k], 0.0) for k in range(entry_i + 1, exit_i + 1))
            fund_pnl = fund_sum * (-side)  # short nhan funding duong
            net = ret + fund_pnl - cost_bps / 10_000
            trades.append(
                {
                    "symbol": sym,
                    "entry_day": d,
                    "days": exit_i - i,
                    "ret": ret,
                    "funding": fund_pnl,
                    "net": net,
                    "side": side,
                }
            )
            busy_until = exit_i
    return trades


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"n": 0}
    nets = [t["net"] for t in trades]
    mean = sum(nets) / len(nets)
    var = sum((x - mean) ** 2 for x in nets) / max(1, len(nets) - 1)
    sd = var**0.5
    by_sym: dict[str, list[float]] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t["net"])
    return {
        "n": len(nets),
        "hit_pct": round(sum(1 for x in nets if x > 0) / len(nets), 4),
        "mean_bps": round(mean * 10_000, 2),
        "median_bps": round(sorted(nets)[len(nets) // 2] * 10_000, 2),
        "t_stat": round(mean / (sd / len(nets) ** 0.5), 2) if sd > 0 else None,
        "avg_hold_days": round(sum(t["days"] for t in trades) / len(trades), 2),
        "funding_bps": round(sum(t["funding"] for t in trades) / len(trades) * 10_000, 2),
        "symbols_positive_pct": round(
            sum(1 for v in by_sym.values() if sum(v) / len(v) > 0) / len(by_sym), 3
        ),
        "by_symbol_mean_bps": {
            s: round(sum(v) / len(v) * 10_000, 1) for s, v in sorted(by_sym.items())
        },
    }


def portfolio_curve(
    trades: list[dict[str, Any]], days: list[int], *, leverage: float = 1.0
) -> dict[str, Any]:
    """Equity theo ngày: mỗi trade chiếm 1/MAX_POS gross; nhân leverage."""
    per_day: dict[int, float] = {d: 0.0 for d in days}
    idx = {d: i for i, d in enumerate(days)}
    for t in trades:
        i0 = idx.get(t["entry_day"])
        if i0 is None:
            continue
        # Moi trade chiem 1/MAX_POS gross; leverage nhan len toan bo
        w = leverage / MAX_POS
        net_per_day = t["net"] / max(1, t["days"]) * w
        for k in range(i0 + 1, min(i0 + t["days"] + 1, len(days))):
            per_day[days[k]] += net_per_day
    equity = 1.0
    peak = 1.0
    dd = 0.0
    daily: list[float] = []
    for d in days:
        r = per_day[d]
        equity *= 1.0 + r
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak)
        daily.append(r)
    years = len(days) / 365
    cagr = equity ** (1 / years) - 1 if years > 0 and equity > 0 else -1.0
    return {
        "leverage": leverage,
        "total_return_pct": round((equity - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_dd_pct": round(dd * 100, 2),
        "usd_end_300": round(300 * equity, 2),
    }


def sma_filter_curve(
    px: list[float],
    days: list[int],
    *,
    sma_n: int = 200,
    leverage: float = 1.0,
    allow_short: bool = False,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    """Benchmark beta: long khi close > SMA(n), flat (hoac short) khi duoi.

    Tra them `worst_day_pct` va `liq_days`: so ngay bi adverse >= nguong thanh ly
    xap xi (1/leverage - MMR 0.5%). Day la uoc luong, khong phai mo phong thanh ly
    intrabar that (du lieu ngay khong thay duoc thu tu trong ngay).
    """
    n = len(px)
    if n <= sma_n:
        return {"n_days": n}
    sma: list[float | None] = [None] * n
    run = 0.0
    for i, p in enumerate(px):
        run += p
        if i >= sma_n:
            run -= px[i - sma_n]
        if i >= sma_n - 1:
            sma[i] = run / sma_n
    equity = 1.0
    peak = 1.0
    dd = 0.0
    daily: list[float] = []
    prev_w = 0.0
    worst = 0.0
    liq_days = 0
    liq_threshold = max(0.05, 1.0 / max(1.0, leverage) - 0.005)
    for i in range(1, n):
        w = 0.0
        if sma_n <= 1:
            w = leverage
        elif sma[i] is not None:
            w = leverage if px[i] > sma[i] else (-leverage if allow_short else 0.0)
        ret = px[i] / px[i - 1] - 1.0
        cost = abs(w - prev_w) * cost_bps / 10_000
        net = w * ret - cost
        if w != 0:
            worst = min(worst, w * ret)
            if abs(w * ret) >= liq_threshold:
                liq_days += 1
        equity *= 1.0 + net
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak)
        daily.append(net)
        prev_w = w
    years = len(daily) / 365
    cagr = equity ** (1 / years) - 1 if years > 0 and equity > 0 else -1.0
    mean = sum(daily) / len(daily)
    var = sum((x - mean) ** 2 for x in daily) / max(1, len(daily) - 1)
    vol = var**0.5
    return {
        "n_days": len(daily),
        "leverage": leverage,
        "allow_short": allow_short,
        "total_return_pct": round((equity - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * (365**0.5) * 100, 2),
        "sharpe": round(mean / vol * (365**0.5), 2) if vol > 0 else None,
        "max_dd_pct": round(dd * 100, 2),
        "worst_day_pct": round(worst * 100, 2),
        "liq_days": liq_days,
        "liq_threshold_pct": round(liq_threshold * 100, 1),
        "usd_end_300": round(300 * equity, 2),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1.4d: funding cuc tri + xsmom universe rong")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/reports/p1.4d-wide.json")
    args = ap.parse_args(argv)

    t0 = time.time()
    data_dir = Path(args.data_dir)
    cache = data_dir / "carry"
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    from concurrent.futures import ThreadPoolExecutor

    def _one(sym: str):
        perp = carry_lab.load_hourly("perp", sym, start, end, cache)
        return sym, perp

    closes_h: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, perp in pool.map(_one, symbols):
            closes_h[sym] = perp

    closes = {s: daily_closes(v) for s, v in closes_h.items() if v}
    fund: dict[str, dict[int, float]] = {}

    def _fund(sym: str) -> tuple[str, dict[int, float]]:
        rates, _ok = carry_lab.funding_mod.load_or_fetch(data_dir, sym, start, end)
        return sym, funding_days(rates)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, fdays in pool.map(_fund, sorted(closes)):
            fund[sym] = fdays
    days = sorted({d for px in closes.values() for d in px})
    print(f"symbol co du lieu: {len(closes)} | ngay: {len(days)}", flush=True)

    out: dict[str, Any] = {"period": {"start": args.start, "end": args.end}, "runs": {}}
    for mode, thr in (("short", 0.30), ("short", 0.60), ("short", 1.20), ("long", 0.30)):
        for hold in (1, 3):
            key = f"{mode}_thr{thr:g}_h{hold}"
            trades = funding_extreme_trades(
                closes, fund, days, threshold_ann=thr, hold=hold, mode=mode
            )
            st = trade_stats(trades)
            cyc = portfolio_curve(trades, days, leverage=1.0)
            out["runs"][key] = {"stats": st, "curve_1x": cyc}
            print(
                f"{key:20s} n={st.get('n', 0):4d} hit={st.get('hit_pct')} "
                f"mean={st.get('mean_bps')}bps fund={st.get('funding_bps')}bps "
                f"t={st.get('t_stat')}  CAGR={cyc.get('cagr_pct')}% DD={cyc.get('max_dd_pct')}%",
                flush=True,
            )

    # XSMOM trên universe rộng (so sánh, chiều ngày)
    common = sorted(set.intersection(*(set(px) for px in closes.values()))) if closes else []
    px_list = {s: [closes[s][d] for d in common] for s in closes}
    rets = pl.returns_by_day(px_list)
    for lb in (7, 30):
        w = pl.xs_weights(px_list, lookback=lb, hold=7, top_n=5)
        st = pl.simulate(w, rets, fund, common, cost_bps=10)
        out["runs"][f"xsmom{lb}_wide"] = st
        print(
            f"xsmom{lb}_wide        CAGR={st.get('cagr_pct')}% Sharpe={st.get('sharpe')} "
            f"DD={st.get('max_dd_pct')}% phi={st.get('cost_drag_pct')}%",
            flush=True,
        )

    # Benchmark beta: BTC trend filter (so sanh "giu BTC" voi chien luoc)
    if "BTCUSDT" in closes:
        btc_days = sorted(closes["BTCUSDT"])
        btc_px = [closes["BTCUSDT"][d] for d in btc_days]
        for lev in (1.0, 2.0, 3.0):
            for short in (False, True):
                key = f"btc_sma200_lev{lev:g}{'_short' if short else ''}"
                st = sma_filter_curve(btc_px, btc_days, sma_n=200, leverage=lev, allow_short=short)
                out["runs"][key] = st
                print(
                    f"{key:26s} CAGR={st.get('cagr_pct')}% Sharpe={st.get('sharpe')} "
                    f"DD={st.get('max_dd_pct')}% 300USD->{st.get('usd_end_300')}",
                    flush=True,
                )
        bh = sma_filter_curve(btc_px, btc_days, sma_n=1, leverage=1.0)
        out["runs"]["btc_buy_hold"] = bh
        print(
            f"{'btc_buy_hold':26s} CAGR={bh.get('cagr_pct')}% Sharpe={bh.get('sharpe')} "
            f"DD={bh.get('max_dd_pct')}% 300USD->{bh.get('usd_end_300')}",
            flush=True,
        )

    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
