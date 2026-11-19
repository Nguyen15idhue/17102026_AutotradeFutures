"""Test funding cực trị (P1.4d): tín hiệu, chiều, funding, không chồng lấn."""

from __future__ import annotations

import pytest

from app.backtest import wide_lab as lab

DAY = lab.DAY_MS


def _days(n: int) -> list[int]:
    return [i * DAY for i in range(n)]


def test_short_signal_uses_funding_annualized_and_holds():
    days = _days(6)
    closes = {"A": {d: 100.0 + i for i, d in enumerate(days)}}
    # funding 0.1%/8h -> 0.3%/ngay -> ~110%/nam
    fund = {"A": {d: 0.003 for d in days}}
    trades = lab.funding_extreme_trades(
        closes, fund, days, threshold_ann=0.30, hold=1, mode="short", cost_bps=20
    )
    assert len(trades) == 3  # ngày 0,2,4 (không chồng lấn)
    t = trades[0]
    assert t["side"] == -1
    assert t["funding"] == pytest.approx(0.003)
    assert t["net"] == pytest.approx(-(101 / 100 - 1) + 0.003 - 0.002, rel=1e-6)


def test_no_signal_below_threshold():
    days = _days(4)
    closes = {"A": {d: 100.0 for d in days}}
    fund = {"A": {d: 0.0001 for d in days}}  # ~3.6%/năm
    trades = lab.funding_extreme_trades(
        closes, fund, days, threshold_ann=0.30, hold=1, mode="short"
    )
    assert trades == []


def test_long_mode_triggers_on_negative_funding():
    days = _days(4)
    closes = {"A": {d: 100.0 for d in days}}
    fund = {"A": {d: -0.003 for d in days}}
    trades = lab.funding_extreme_trades(closes, fund, days, threshold_ann=0.30, hold=1, mode="long")
    assert trades and all(t["side"] == 1 for t in trades)
    assert trades[0]["funding"] > 0  # long tra funding am => nhan funding


def test_portfolio_curve_scales_with_leverage():
    days = _days(4)
    trades = [
        {
            "entry_day": days[0],
            "days": 1,
            "net": 0.10,
            "side": -1,
            "symbol": "A",
            "funding": 0.0,
        }
    ]
    c1 = lab.portfolio_curve(trades, days, leverage=1.0)
    c2 = lab.portfolio_curve(trades, days, leverage=2.0)
    assert c1["total_return_pct"] == pytest.approx(2.0, abs=1e-6)  # 10% / 5 vi the
    assert c2["total_return_pct"] == pytest.approx(4.0, abs=1e-6)


def test_sma_filter_buy_hold_matches_price_growth():
    days = _days(5)
    px = [100.0, 110.0, 121.0, 133.1, 146.41]
    st = lab.sma_filter_curve(px, days, sma_n=1, leverage=1.0, cost_bps=0.0)
    assert st["total_return_pct"] == pytest.approx(46.41, rel=1e-3)
    assert st["max_dd_pct"] == 0.0
    assert st["usd_end_300"] == pytest.approx(300 * 1.4641, rel=1e-3)


def test_sma_filter_goes_flat_below_sma():
    # tang 30 ngay roi sap manh: filter phai cat lo phan sau
    days = _days(60)
    px = [100.0 * (1.001**i) for i in range(35)] + [100.0 * (0.97**i) for i in range(1, 26)]
    st = lab.sma_filter_curve(px, days, sma_n=10, leverage=1.0)
    bh = lab.sma_filter_curve(px, days, sma_n=1, leverage=1.0)
    assert st["max_dd_pct"] < bh["max_dd_pct"]


def test_sma_filter_leverage_scales_signal():
    days = _days(3)
    px = [100.0, 110.0, 121.0]
    c1 = lab.sma_filter_curve(px, days, sma_n=1, leverage=1.0)
    c3 = lab.sma_filter_curve(px, days, sma_n=1, leverage=3.0)
    assert c3["usd_end_300"] > c1["usd_end_300"]
