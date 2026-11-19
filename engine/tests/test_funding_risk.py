"""Test funding-long qua risk engine: size, cap vị thế, margin, halt."""

from __future__ import annotations

from pathlib import Path

from app import config as config_mod
from app.backtest import funding_risk as fr

ROOT = Path(__file__).resolve().parents[2]
CFG = config_mod.load(ROOT / "config" / "mvp.mock.yaml")
DAY = fr.DAY_MS


def _series(n: int, base: float = 100.0, drift: float = 0.0) -> dict[int, float]:
    return {i * DAY: base * (1 + drift) ** i for i in range(n)}


def test_sizing_respects_risk_and_caps():
    n = 40
    closes = {f"S{i}": _series(n, 100.0 + i) for i in range(5)}
    fund = {s: {d: -0.01 for d in px} for s, px in closes.items()}  # rất âm -> tín hiệu
    days = sorted(closes["S0"])
    out = fr.run(closes, fund, days, CFG, threshold_ann=0.30, hold=3, dd_halt=False)
    assert out["entries"] > 0
    assert out["max_concurrent"] <= CFG.strategies.max_positions_per_strategy
    # leverage trần 3x
    assert out["max_gross_over_equity"] <= CFG.risk.max_leverage + 1e-9


def test_dd_halt_stops_entries():
    n = 60
    # giá giảm mạnh để DD vượt 6%
    closes = {"A": _series(n, 100.0, -0.05), "B": _series(n, 100.0, -0.05)}
    fund = {s: {d: -0.01 for d in px} for s, px in closes.items()}
    days = sorted(closes["A"])
    out = fr.run(closes, fund, days, CFG, threshold_ann=0.30, hold=7, dd_halt=True)
    assert out["max_dd_pct"] >= CFG.risk.max_drawdown * 100 - 1e-9
    assert out["halted"] is True


def test_no_signal_no_trade():
    n = 30
    closes = {"A": _series(n)}
    fund = {"A": {d: 0.0001 for d in closes["A"]}}  # funding dương -> không tín hiệu long
    days = sorted(closes["A"])
    out = fr.run(closes, fund, days, CFG, threshold_ann=0.30, hold=3, dd_halt=True)
    assert out["entries"] == 0
    assert out["net_usd"] == 0


def test_holding_time_exit_is_counted():
    n = 40
    closes = {"A": _series(n, 100.0, 0.002)}
    fund = {"A": {d: -0.01 for d in closes["A"]}}
    days = sorted(closes["A"])
    out = fr.run(closes, fund, days, CFG, threshold_ann=0.30, hold=3, dd_halt=False)
    assert out["counts"]["exit_time"] >= 1
