"""Test carry delta-neutral: basis, funding, phí, thống kê."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.backtest import carry_lab as lab


def _ms(y, m, d) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def test_month_cycles_groups_by_month():
    spot = {_ms(2026, 1, 2): 1.0, _ms(2026, 1, 20): 1.0, _ms(2026, 2, 3): 1.0}
    out = lab.month_cycles(spot)
    assert set(out) == {"2026-01", "2026-02"}
    assert out["2026-01"] == (_ms(2026, 1, 2), _ms(2026, 1, 20))


def test_cycle_return_basis_and_funding_and_fees():
    t0, t1 = _ms(2026, 1, 1), _ms(2026, 1, 31)
    spot = {t0: 100.0, t1: 110.0}  # +10%
    perp = {t0: 100.0, t1: 108.0}  # +8% -> basis +2%
    funding = {t0: 0.002, t0 + 1: 0.003}  # +0.5%
    r = lab.cycle_return(spot, perp, funding, t0, t1, fee_bps=38)
    assert r == pytest.approx(0.02 + 0.005 - 0.0038)


def test_cycle_return_none_when_missing_price():
    t0, t1 = _ms(2026, 1, 1), _ms(2026, 1, 31)
    assert lab.cycle_return({t0: 1.0}, {t0: 1.0, t1: 1.0}, {}, t0, t1, fee_bps=0) is None


def test_stats_compounding_and_dd():
    st = lab.stats([0.01, 0.01, -0.02, 0.01], periods_per_year=12)
    assert st["n"] == 4
    assert st["total_return_pct"] == pytest.approx((1.01 * 1.01 * 0.98 * 1.01 - 1) * 100, abs=0.01)
    assert st["worst_month_pct"] == pytest.approx(-2.0)
    assert st["hit_pct"] == 0.75


def test_stats_negative_equity_guard():
    st = lab.stats([-1.0], periods_per_year=12)
    assert st["cagr_pct"] == -100.0
