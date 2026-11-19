"""Funding-long chạy QUA risk engine (P1.4e).

Khác `wide_lab`: đây không phải mô phỏng vector hoá bỏ qua risk. Mọi lệnh phải qua:
  - risk/lệnh (config, mặc định 0,5% equity)
  - max_positions (4) + max_positions_per_strategy (2)
  - portfolio risk <= 2% equity, correlated risk <= 2% (mock)
  - margin sử dụng <= 60% equity, leverage <= 3x
  - daily loss 2% / weekly 4% / max DD 6% (halt nếu bật)
  - max_orders_per_day (10)

Mục đích: trả lời câu "kết quả trên có tuân thủ risk engine không" bằng một lần chạy
có ràng buộc thật, cùng dữ liệu và cùng tín hiệu.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .. import config as config_mod
from . import carry_lab
from . import funding as funding_mod
from . import wide_lab as wl

DAY_MS = 86_400_000


@dataclass
class Pos:
    symbol: str
    qty: float
    entry: float
    stop: float
    entry_day: int
    hold_days: int
    risk_usd: float
    notional: float
    funding_paid: float = 0.0


@dataclass
class State:
    equity: float
    peak: float
    max_dd: float = 0.0
    realized: float = 0.0
    open: list[Pos] = field(default_factory=list)
    day_start_eq: float = 0.0
    week_start_eq: float = 0.0
    day_key: int = -1
    week_key: int = -1
    orders_today: int = 0
    halted: bool = False
    halt_day: int | None = None
    max_concurrent: int = 0
    max_notional_ratio: float = 0.0
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "entries": 0,
            "reject_slots": 0,
            "reject_risk": 0,
            "reject_margin": 0,
            "reject_daily_loss": 0,
            "reject_orders_day": 0,
            "exit_stop": 0,
            "exit_time": 0,
            "exit_end": 0,
        }
    )
    trades: list[dict[str, Any]] = field(default_factory=list)


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def run(
    closes: dict[str, dict[int, float]],
    fund: dict[str, dict[int, float]],
    days: list[int],
    cfg: config_mod.Config,
    *,
    threshold_ann: float = 0.30,
    hold: int = 3,
    dd_halt: bool = True,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    risk = cfg.risk
    st = State(equity=cfg.equity_base, peak=cfg.equity_base)
    idx_by_day = {d: i for i, d in enumerate(days)}

    def _mtm(day: int) -> float:
        eq = cfg.equity_base + st.realized
        for p in st.open:
            px = closes.get(p.symbol, {}).get(day)
            if px:
                eq += (px - p.entry) * p.qty
        return eq

    for i, d in enumerate(days):
        day_key = d // DAY_MS
        if day_key != st.day_key:
            st.day_key = day_key
            st.day_start_eq = st.equity
            st.orders_today = 0
        week_key = d // (7 * DAY_MS)
        if week_key != st.week_key:
            st.week_key = week_key
            st.week_start_eq = st.equity

        # --- funding + exits ---
        for p in list(st.open):
            rate = fund.get(p.symbol, {}).get(d, 0.0)
            p.funding_paid += rate * p.notional  # long tra funding; rate am -> nhan
            px = closes.get(p.symbol, {}).get(d)
            if px is None:
                continue
            if px <= p.stop:
                _close(st, p, p.stop, d, "stop", cost_bps)
                st.counts["exit_stop"] += 1
            elif i - idx_by_day.get(p.entry_day, i) >= p.hold_days:
                _close(st, p, px, d, "time", cost_bps)
                st.counts["exit_time"] += 1

        st.equity = cfg.equity_base + st.realized
        mtm = _mtm(d)
        st.peak = max(st.peak, mtm)
        if st.peak > 0:
            st.max_dd = max(st.max_dd, (st.peak - mtm) / st.peak * 100)
        if dd_halt and st.max_dd >= risk.max_drawdown * 100:
            if not st.halted:
                st.halted = True
                st.halt_day = d

        # --- entries ---
        if st.halted:
            continue
        if st.equity - st.day_start_eq <= -risk.daily_loss_limit * st.day_start_eq:
            st.counts["reject_daily_loss"] += 1
            continue
        if st.equity - st.week_start_eq <= -risk.weekly_loss_limit * st.week_start_eq:
            continue
        if st.orders_today >= cfg.execution.max_orders_per_day:
            st.counts["reject_orders_day"] += 1
            continue

        for sym in sorted(closes):
            f = fund.get(sym, {}).get(d)
            if f is None or wl._ann(f) >= -threshold_ann:
                continue
            if any(p.symbol == sym for p in st.open):
                continue
            if len(st.open) >= risk.max_positions or len(st.open) >= (
                cfg.strategies.max_positions_per_strategy
            ):
                st.counts["reject_slots"] += 1
                continue
            px = closes[sym].get(d)
            hist = [closes[sym][k] for k in days[max(0, i - 20) : i] if k in closes[sym]]
            if px is None or len(hist) < 5:
                continue
            rets = [hist[j] / hist[j - 1] - 1.0 for j in range(1, len(hist))]
            stop_dist = max(3.0 * _std(rets) * px, px * 0.02)  # toi thieu 2%
            stop = px - stop_dist
            risk_usd = risk.risk_per_trade * st.equity
            qty = risk_usd / stop_dist
            notional = qty * px
            # leverage cap va margin cap
            max_notional = risk.max_leverage * st.equity
            if notional > max_notional:
                qty = max_notional / px
                notional = max_notional
                risk_usd = qty * stop_dist
            used_margin = sum(p.notional / risk.max_leverage for p in st.open)
            if used_margin + notional / risk.max_leverage > risk.margin_usage_max * st.equity:
                st.counts["reject_margin"] += 1
                continue
            if sum(p.risk_usd for p in st.open) + risk_usd > risk.portfolio_risk_max * st.equity:
                st.counts["reject_risk"] += 1
                continue
            if notional < 5:
                continue
            st.open.append(
                Pos(
                    symbol=sym,
                    qty=qty,
                    entry=px,
                    stop=stop,
                    entry_day=d,
                    hold_days=hold,
                    risk_usd=risk_usd,
                    notional=notional,
                )
            )
            st.orders_today += 1
            st.counts["entries"] += 1
            st.max_concurrent = max(st.max_concurrent, len(st.open))
            st.max_notional_ratio = max(
                st.max_notional_ratio,
                sum(p.notional for p in st.open) / max(1e-9, st.equity),
            )

    # dong cuoi ky
    last = days[-1]
    for p in list(st.open):
        px = closes.get(p.symbol, {}).get(last, p.entry)
        _close(st, p, px, last, "end", cost_bps)
        st.counts["exit_end"] += 1

    st.equity = cfg.equity_base + st.realized
    equity_curve = [cfg.equity_base + t["realized"] for t in st.trades]
    years = len(days) / 365
    cagr = (st.equity / cfg.equity_base) ** (1 / years) - 1 if years > 0 else -1.0
    return {
        "threshold_ann": threshold_ann,
        "hold": hold,
        "dd_halt": dd_halt,
        "n_days": len(days),
        "entries": st.counts["entries"],
        "net_usd": round(st.realized, 2),
        "equity_end": round(st.equity, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_dd_pct": round(st.max_dd, 2),
        "halted": st.halted,
        "halt_day": st.halt_day,
        "max_concurrent": st.max_concurrent,
        "max_gross_over_equity": round(st.max_notional_ratio, 2),
        "counts": st.counts,
        "avg_hold": round(
            sum((t["exit_day"] - t["entry_day"]) / DAY_MS for t in st.trades)
            / max(1, len(st.trades)),
            2,
        ),
        "worst_trade_pct": round(
            min((t["pnl"] / max(1e-9, t["risk_usd"]) for t in st.trades), default=0.0), 2
        ),
        "equity_curve_tail": equity_curve[-5:],
    }


def _close(st: State, p: Pos, px: float, day: int, reason: str, cost_bps: float) -> None:
    gross = (px - p.entry) * p.qty
    fees = (p.entry + px) * p.qty * cost_bps / 10_000
    pnl = gross - fees - p.funding_paid
    st.realized += pnl
    st.trades.append(
        {
            "symbol": p.symbol,
            "entry_day": p.entry_day,
            "exit_day": day,
            "pnl": pnl,
            "risk_usd": p.risk_usd,
            "reason": reason,
            "realized": st.realized,
        }
    )
    for k, v in enumerate(st.open):
        if v is p:
            st.open.pop(k)
            break


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Funding-long qua risk engine")
    ap.add_argument("--config", default="config/mvp.mock.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument(
        "--symbols",
        default=(
            "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,"
            "LINKUSDT,SUIUSDT,TRXUSDT,TONUSDT,APTUSDT,ARBUSDT,OPUSDT,NEARUSDT,"
            "ATOMUSDT,FILUSDT,INJUSDT,LTCUSDT,DOTUSDT,UNIUSDT,AAVEUSDT,ETCUSDT"
        ),
    )
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-11-01")
    ap.add_argument("--out", default="data/reports/p1.4e-funding-risk.json")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    data_dir = Path(args.data_dir)
    cache = data_dir / "carry"
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def _one(sym: str):
        return sym, carry_lab.load_hourly("perp", sym, start, end, cache)

    closes: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, perp in pool.map(_one, symbols):
            if perp:
                closes[sym] = wl.daily_closes(perp)

    def _fund(sym: str):
        rates, _ok = funding_mod.load_or_fetch(data_dir, sym, start, end)
        return sym, wl.funding_days(rates)

    fund: dict[str, dict[int, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, fdays in pool.map(_fund, sorted(closes)):
            fund[sym] = fdays
    days = sorted({d for px in closes.values() for d in px})
    print(f"symbol={len(closes)} ngay={len(days)} risk={cfg.risk.risk_per_trade}", flush=True)

    out = {
        "period": {"start": args.start, "end": args.end},
        "risk_config": {
            "risk_per_trade": cfg.risk.risk_per_trade,
            "max_positions": cfg.risk.max_positions,
            "max_positions_per_strategy": cfg.strategies.max_positions_per_strategy,
            "portfolio_risk_max": cfg.risk.portfolio_risk_max,
            "margin_usage_max": cfg.risk.margin_usage_max,
            "leverage": cfg.risk.max_leverage,
        },
        "runs": {},
    }
    for thr, hold in ((0.30, 3), (0.50, 3), (0.20, 7)):
        for halt in (True, False):
            key = f"thr{thr:g}_h{hold}_halt{int(halt)}"
            out["runs"][key] = run(
                closes, fund, days, cfg, threshold_ann=thr, hold=hold, dd_halt=halt
            )
            r = out["runs"][key]
            print(
                f"{key:24s} entries={r['entries']:4d} net={r['net_usd']:8.2f} "
                f"CAGR={r['cagr_pct']:7.2f}% DD={r['max_dd_pct']:5.2f}% halted={r['halted']}",
                flush=True,
            )
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"xong {round(time.time() - t0, 1)}s -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
