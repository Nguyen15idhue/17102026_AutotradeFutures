"""Tong hop ket qua backtest theo strategy/side/coin/slice + cong nghiem thu P1.4."""

from __future__ import annotations

from typing import Any

from .sim import Trade

MR = "mean_reversion"
TREND = "trend_pullback"


def _dd_pct(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    worst = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            worst = max(worst, (peak - e) / peak * 100)
    return worst


def stats(trades: list[Trade], equity_base: float) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "wins": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "avg_r": 0.0,
            "net": 0.0,
            "gross": 0.0,
            "fees": 0.0,
            "funding": 0.0,
            "fees_over_gross": None,
            "realized_dd_pct": 0.0,
            "max_consec_losses": 0,
            "avg_hold_h": 0.0,
        }
    wins = sum(1 for t in trades if t.win)
    net = sum(t.pnl for t in trades)
    gross = sum(t.pnl_gross for t in trades)
    fees = sum(t.fees for t in trades)
    funding = sum(t.funding for t in trades)
    eq = equity_base
    curve = [eq]
    streak = worst_streak = 0
    for t in sorted(trades, key=lambda x: x.exit_ms):
        eq += t.pnl
        curve.append(eq)
        streak = 0 if t.win else streak + 1
        worst_streak = max(worst_streak, streak)
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 4),
        "expectancy_r": round(sum(t.r_multiple for t in trades) / n, 4),
        "avg_r": round(sum(t.r_multiple for t in trades) / n, 4),
        "net": round(net, 2),
        "gross": round(gross, 2),
        "fees": round(fees, 2),
        "funding": round(funding, 2),
        "fees_over_gross": round(fees / gross, 4) if gross > 0 else None,
        "realized_dd_pct": round(_dd_pct(curve), 2),
        "max_consec_losses": worst_streak,
        "avg_hold_h": round(sum((t.exit_ms - t.entry_ms) for t in trades) / n / 3_600_000, 2),
    }


def _group(trades: list[Trade], key) -> dict[str, dict[str, Any]]:
    out: dict[str, list[Trade]] = {}
    for t in trades:
        out.setdefault(str(key(t)), []).append(t)
    return {k: v for k, v in sorted(out.items())}


def build(
    trades: list[Trade],
    *,
    equity_base: float,
    slices: list[Any],
    sim_summary: dict[str, Any],
    data_summary: dict[str, Any],
) -> dict[str, Any]:
    by_strategy = {
        k: stats(v, equity_base) for k, v in _group(trades, lambda t: t.strategy_id).items()
    }
    by_side = {
        k: stats(v, equity_base)
        for k, v in _group([t for t in trades if t.strategy_id == TREND], lambda t: t.side).items()
    }
    by_symbol_mr = {
        k: stats(v, equity_base)
        for k, v in _group([t for t in trades if t.strategy_id == MR], lambda t: t.symbol).items()
    }
    by_symbol_trend = {
        k: stats(v, equity_base)
        for k, v in _group(
            [t for t in trades if t.strategy_id == TREND], lambda t: t.symbol
        ).items()
    }
    by_slice = {k: stats(v, equity_base) for k, v in _group(trades, lambda t: t.slice).items()}
    by_reason = {k: stats(v, equity_base) for k, v in _group(trades, lambda t: t.reason).items()}
    by_strategy_exit: dict[str, dict[str, dict[str, Any]]] = {}
    for strat in sorted({t.strategy_id for t in trades}):
        sub = [t for t in trades if t.strategy_id == strat]
        by_strategy_exit[strat] = {
            k: stats(v, equity_base) for k, v in _group(sub, lambda t: t.reason).items()
        }
    report = {
        "overall": stats(trades, equity_base),
        "by_strategy": by_strategy,
        "trend_by_side": by_side,
        "mr_by_symbol": by_symbol_mr,
        "trend_by_symbol": by_symbol_trend,
        "by_slice": dict(sorted(by_slice.items())),
        "by_exit_reason": by_reason,
        "by_strategy_exit": by_strategy_exit,
        "sim": sim_summary,
        "data": data_summary,
        "slices": [
            {"name": s.name, "kind": s.kind, "start_ms": s.start_ms, "end_ms": s.end_ms}
            for s in slices
        ],
    }
    report["gates"] = gates(report)
    return report


def gates(report: dict[str, Any]) -> list[dict[str, Any]]:
    """8 cong nghiem thu P1.4 (docs/phase1_task.md). Khong tu noi nguong."""
    mr = report["by_strategy"].get(MR) or stats([], 0)
    sides = report.get("trend_by_side") or {}
    coins = report.get("mr_by_symbol") or {}
    positive_coins = sum(1 for v in coins.values() if v["net"] > 0)
    coin_ratio = positive_coins / len(coins) if coins else 0.0
    fees_ratio = mr["fees_over_gross"]
    dd = report["sim"].get("max_dd_pct", 0.0)
    return [
        {"id": 1, "name": "MR >= 150 lenh", "ok": mr["n"] >= 150, "value": mr["n"]},
        {
            "id": 2,
            "name": "Expectancy MR > 0",
            "ok": mr["expectancy_r"] > 0,
            "value": mr["expectancy_r"],
        },
        {"id": 3, "name": "Max DD < 8%", "ok": dd < 8.0, "value": round(dd, 2)},
        {
            "id": 4,
            "name": "Duong tren >= 60% coin",
            "ok": coin_ratio >= 0.6,
            "value": round(coin_ratio, 3),
        },
        {
            "id": 5,
            "name": "Out-of-sample da chay 1 lan",
            "ok": any(k.upper().startswith("OOS") for k in (report.get("by_slice") or {})),
            "value": [k for k in (report.get("by_slice") or {}) if k.upper().startswith("OOS")],
        },
        {
            "id": 6,
            "name": "Fees/gross < 30%",
            "ok": fees_ratio is not None and fees_ratio < 0.30,
            "value": fees_ratio,
        },
        {
            "id": 7,
            "name": "Trend >= 20 lenh/nhanh",
            "ok": all((sides.get(s) or {}).get("n", 0) >= 20 for s in ("LONG", "SHORT")),
            "value": {s: (sides.get(s) or {}).get("n", 0) for s in ("LONG", "SHORT")},
        },
        {
            "id": 8,
            "name": "Trend bao cao rieng long/short",
            "ok": bool(sides),
            "value": sorted(sides),
        },
    ]
