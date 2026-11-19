"""Test phòng thử danh mục: trọng số, mô phỏng, phí, funding, tổng hợp ngày."""

from __future__ import annotations

import pytest

from app.backtest import portfolio_lab as lab

DAY = lab.DAY_MS


def _daily_bars(prices, start_day=0):
    return [
        {
            "day": (start_day + i) * DAY,
            "o": p,
            "h": p * 1.01,
            "l": p * 0.99,
            "c": p,
            "v": 1.0,
            "n": 1440,
        }
        for i, p in enumerate(prices)
    ]


def test_load_daily_aggregates_bars(tmp_path):
    from app.data import parquet_io

    bars = []
    start = 0
    for i in range(2880):  # 2 ngày
        px = 100.0 + i * 0.01
        bars.append(
            {
                "open_time": start + i * 60_000,
                "close_time": start + i * 60_000 + 59_999,
                "o": px,
                "h": px + 1,
                "l": px - 1,
                "c": px,
                "v": 2.0,
                "closed": True,
            }
        )
    parquet_io.save_day(tmp_path / "market", "TESTUSDT", "1m", "1970-01-01", bars[:1440])
    parquet_io.save_day(tmp_path / "market", "TESTUSDT", "1m", "1970-01-02", bars[1440:])
    out = lab.load_daily(tmp_path / "market", "TESTUSDT", 0, 10 * DAY)
    assert len(out) == 2
    assert out[0]["h"] == max(b["h"] for b in bars[:1440])
    assert out[1]["c"] == bars[-1]["c"]


def test_xs_weights_long_strong_short_weak():
    closes = {"A": [1, 1, 1, 10], "B": [1, 1, 1, 1], "C": [1, 1, 1, 0.1]}
    w = lab.xs_weights(closes, lookback=3, hold=1, top_n=1)
    assert w["A"][-1] == pytest.approx(0.5)
    assert w["C"][-1] == pytest.approx(-0.5)
    assert w["B"][-1] == 0.0


def test_xs_weights_reverse_flips():
    closes = {"A": [1, 1, 1, 10], "B": [1, 1, 1, 1], "C": [1, 1, 1, 0.1]}
    w = lab.xs_weights(closes, lookback=3, hold=1, top_n=1, reverse=True)
    assert w["A"][-1] == pytest.approx(-0.5)
    assert w["C"][-1] == pytest.approx(0.5)


def test_tsmom_weights_sign():
    closes = {"A": [float(i) for i in range(1, 20)], "B": [float(100 - i) for i in range(1, 20)]}
    w = lab.tsmom_weights(closes, fast=3, slow=5)
    assert w["A"][-1] > 0 and w["B"][-1] < 0


def test_donchian_enters_on_breakout_and_exits():
    prices = [10.0] * 25 + [12.0, 11.5, 11.4, 11.3, 11.2, 10.95]
    daily = {"A": _daily_bars(prices)}
    days = [b["day"] for b in daily["A"]]
    w = lab.donchian_weights(daily, days, entry_n=20, exit_n=5)
    series = w["A"]
    assert series[25] > 0  # phá đỉnh 20 ngày
    assert series[-1] == 0  # thủng đáy 5 ngày -> thoát, chưa đủ xa để short


def test_simulate_equity_costs_and_funding():
    days = [i * DAY for i in range(5)]
    rets = {"A": [0.0, 0.01, 0.01, 0.01, 0.01]}
    weights = {"A": [1.0] * 5}
    st = lab.simulate(weights, rets, {}, days, cost_bps=10)
    expected = (1.01 - 0.001) * 1.01**3
    assert st["equity_end"] == pytest.approx(expected, abs=5e-4)

    # short + funding duong -> duoc huong funding
    weights_short = {"A": [-1.0] * 5}
    fund = {"A": {d: 0.0001 for d in days}}
    st2 = lab.simulate(weights_short, {"A": [0.0] * 5}, fund, days, cost_bps=0)
    assert st2["equity_end"] > 1.0
    assert st2["funding_pnl_pct"] == pytest.approx(0.04, rel=0.2)


def test_funding_by_day_sums_rates():
    r = {0: 0.0001, 8 * 3600 * 1000: 0.0002, DAY: 0.0003}
    out = lab.funding_by_day(r)
    assert out[0] == pytest.approx(0.0003)
    assert out[DAY] == pytest.approx(0.0003)


def test_funding_weights_short_high_funding():
    days = [i * DAY for i in range(10)]
    fund = {
        "A": {d: 0.001 for d in days},
        "B": {d: 0.0 for d in days},
        "C": {d: -0.001 for d in days},
    }
    w = lab.funding_weights(fund, days, lookback=3, top_n=1)
    assert w["A"][-1] < 0
    assert w["C"][-1] > 0
