"""Test alt-lab: thống kê theo tháng và giới hạn gross."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.backtest import alt_lab as lab

DAY = lab.DAY_MS


def _ms(y, m, d) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def test_monthly_stats_matches_hand_calc():
    days = [_ms(2026, 1, 2), _ms(2026, 1, 30), _ms(2026, 2, 2), _ms(2026, 2, 27)]
    curve = [1.10, 1.10, 0.99, 1.023]  # tháng 1 +10%, tháng 2: 1.023/1.10-1 = -7%
    st = lab.monthly_stats(curve, days)
    assert st["n_months"] == 2
    assert st["mean_pct"] == pytest.approx((10.0 - 7.0) / 2, abs=0.1)
    assert st["best_pct"] == pytest.approx(10.0, abs=0.1)
    assert st["worst_pct"] == pytest.approx(-7.0, abs=0.1)
    assert st["pct_months_ge5"] == 0.5
    assert st["pct_months_le_neg10"] == 0.0


def test_funding_dip_weights_respects_gross_and_threshold():
    days = [i * DAY for i in range(30)]
    closes = {f"S{i}": {d: 100.0 + i for d in days} for i in range(6)}
    fund = {s: {d: (-0.01 if i % 3 == 0 else 0.0001) for i, d in enumerate(days)} for s in closes}
    w = lab.funding_dip_weights(closes, fund, days, threshold=0.30, hold=3, max_pos=5, gross=2.0)
    for i in range(len(days)):
        assert sum(abs(w[s][i]) for s in w) <= 2.0 + 1e-9
    # ngày funding dương -> không vào thêm (không có weight mới)
    assert any(v > 0 for s in w for v in w[s])


def test_funding_dip_weights_no_signal_when_funding_positive():
    days = [i * DAY for i in range(10)]
    closes = {"S0": {d: 100.0 for d in days}}
    fund = {"S0": {d: 0.001 for d in days}}
    w = lab.funding_dip_weights(closes, fund, days, threshold=0.30, hold=3, max_pos=5, gross=1.0)
    assert all(v == 0 for v in w["S0"])
