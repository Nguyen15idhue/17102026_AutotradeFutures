"""Test risk limits P1.3: moi ly do reject 1 ca, theo thu tu fail-fast."""

from __future__ import annotations

from app.risk import limits as L
from app.risk.types import OrderRequest, Position, RiskInputs

NOW = 1_000_000


def req(**over) -> OrderRequest:
    base = dict(strategy_id="mean_reversion", symbol="BTCUSDT", side="BUY", entry=100.0, stop=99.0)
    base.update(over)
    return OrderRequest(**base)


def pos(**over) -> Position:
    base = dict(
        symbol="ETHUSDT",
        strategy_id="trend_pullback",
        side="LONG",
        qty=0.1,
        entry=100.0,
        stop=99.0,
        risk_usd=0.5,
        group="ETHUSDT",
    )
    base.update(over)
    return Position(**base)


def inp(**over) -> RiskInputs:
    base = dict(
        now_ms=NOW,
        halted=False,
        last_market_ms=NOW - 500,
        stale_data_seconds=3.0,
        regime="RANGE",
        trend_dir=0,
        blackout_until_ms=0,
        open_positions=(),
        equity=300.0,
        day_pnl=0.0,
        week_pnl=0.0,
        dd_pct=0.0,
        orders_today=0,
        spread_bps=1.0,
        min_notional=5.0,
        step_size=0.001,
        tick_size=0.1,
        available_balance=300.0,
        allow_short=True,
        risk_per_trade=0.0025,
        max_positions=4,
        max_positions_per_strategy=2,
        portfolio_risk_max=0.02,
        max_correlated_risk=0.005,
        margin_usage_max=0.60,
        max_orders_per_day=5,
        leverage=3,
        daily_loss_limit=0.02,
        weekly_loss_limit=0.04,
        max_drawdown=0.06,
    )
    base.update(over)
    return RiskInputs(**base)


def test_ok_baseline():
    d = L.check(req(), inp())
    assert d.ok and d.qty > 0 and d.notional >= 5.0 and d.risk_usd <= 0.75 + 1e-9


def test_halted():
    assert L.check(req(), inp(halted=True)).reason == L.REASON_HALTED


def test_stale_none_and_old():
    assert L.check(req(), inp(last_market_ms=None)).reason == L.REASON_STALE
    assert L.check(req(), inp(last_market_ms=NOW - 4000)).reason == L.REASON_STALE


def test_crisis():
    assert L.check(req(), inp(regime="CRISIS")).reason == L.REASON_CRISIS


def test_blackout():
    assert L.check(req(), inp(blackout_until_ms=NOW + 1)).reason == L.REASON_BLACKOUT
    assert L.check(req(), inp(blackout_until_ms=NOW - 1)).ok


def test_short_not_allowed():
    r = req(side="SELL", entry=100.0, stop=101.0)
    assert L.check(r, inp(allow_short=False)).reason == L.REASON_SHORT_OFF
    assert L.check(r, inp(allow_short=True)).ok


def test_max_orders_day():
    assert L.check(req(), inp(orders_today=5)).reason == L.REASON_MAX_ORDERS


def test_already_open_same_symbol():
    d = L.check(req(), inp(open_positions=(pos(symbol="BTCUSDT"),)))
    assert d.reason == L.REASON_ALREADY_OPEN


def test_slot_global():
    ps = tuple(pos(symbol=f"S{i}USDT", risk_usd=0.1, group=f"g{i}") for i in range(4))
    assert L.check(req(), inp(open_positions=ps)).reason == L.REASON_SLOT_GLOBAL


def test_slot_strategy():
    ps = (
        pos(symbol="AUSDT", strategy_id="mean_reversion", risk_usd=0.1, group="a"),
        pos(symbol="BUSDT", strategy_id="mean_reversion", risk_usd=0.1, group="b"),
    )
    assert L.check(req(), inp(open_positions=ps)).reason == L.REASON_SLOT_STRATEGY


def test_daily_loss():
    assert L.check(req(), inp(day_pnl=-6.0)).reason == L.REASON_DAILY


def test_weekly_loss():
    assert L.check(req(), inp(week_pnl=-12.0)).reason == L.REASON_WEEKLY


def test_max_drawdown():
    assert L.check(req(), inp(dd_pct=0.06)).reason == L.REASON_DD


def test_portfolio_risk():
    ps = (pos(risk_usd=5.5, symbol="AUSDT", group="a"),)
    assert L.check(req(), inp(open_positions=ps)).reason == L.REASON_PORTFOLIO


def test_correlated_cap_same_group():
    ps = (pos(risk_usd=0.8, group=""),)  # group "" = cung nhom fail-closed
    assert L.check(req(group=""), inp(open_positions=ps)).reason == L.REASON_CORRELATED


def test_correlated_other_group_allowed():
    ps = (pos(risk_usd=0.8, group="ETHUSDT"),)
    assert L.check(req(group="SOLUSDT"), inp(open_positions=ps)).ok


def test_margin_cap():
    ps = tuple(
        pos(symbol=f"M{i}USDT", qty=5.0, entry=100.0, risk_usd=0.1, group=f"g{i}") for i in range(3)
    )
    # 3 x (500/3) = 500 margin > 180 -> chan
    assert L.check(req(), inp(open_positions=ps)).reason == L.REASON_MARGIN


def test_margin_over_available_balance():
    assert L.check(req(), inp(available_balance=1.0)).reason == L.REASON_MARGIN


def test_every_reason_is_covered():
    """Moi hang so ly do phai nam trong REASONS de khong co reject 'la'."""
    from app.risk import sizing as S

    used = {
        getattr(mod, n)
        for mod in (L, S)
        for n in dir(mod)
        if n.startswith("REASON_") and isinstance(getattr(mod, n), str)
    }
    assert used == set(L.REASONS)
