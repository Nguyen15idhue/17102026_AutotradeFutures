"""Cac gioi han cung P1.3. Fail-fast theo thu tu, moi ly do la hang chuoi.

Thu tu dat co chu y: chan an toan (halted/stale/crisis/blackout/short) truoc,
roi moi den so luong va ngan sach. Ly do tra ve duoc test truc tiep.
"""

from __future__ import annotations

from .sizing import plan
from .types import OrderRequest, RiskDecision, RiskInputs

REASON_HALTED = "halted"
REASON_PAUSED = "paused"
REASON_STALE = "stale_data"
REASON_CRISIS = "crisis"
REASON_BLACKOUT = "blackout"
REASON_SHORT_OFF = "short_not_allowed"
REASON_MAX_ORDERS = "max_orders_day"
REASON_ALREADY_OPEN = "already_open"
REASON_SLOT_GLOBAL = "slot_global"
REASON_SLOT_STRATEGY = "slot_strategy"
REASON_DAILY = "daily_loss"
REASON_WEEKLY = "weekly_loss"
REASON_DD = "max_drawdown"
REASON_PORTFOLIO = "portfolio_risk"
REASON_CORRELATED = "correlated_risk"
REASON_MARGIN = "margin_cap"

REASONS = (
    REASON_HALTED,
    REASON_PAUSED,
    REASON_STALE,
    REASON_CRISIS,
    REASON_BLACKOUT,
    REASON_SHORT_OFF,
    REASON_MAX_ORDERS,
    REASON_ALREADY_OPEN,
    REASON_SLOT_GLOBAL,
    REASON_SLOT_STRATEGY,
    REASON_DAILY,
    REASON_WEEKLY,
    REASON_DD,
    REASON_PORTFOLIO,
    REASON_CORRELATED,
    REASON_MARGIN,
    "invalid_stop",
    "min_notional",
    "risk_too_large",
)


def _is_short(req: OrderRequest) -> bool:
    return req.side.upper() == "SELL"


def check(req: OrderRequest, inp: RiskInputs) -> RiskDecision:
    """Kiem toan bo gioi han. Tra ve RiskDecision(ok=True) kem qty khi qua het."""
    if inp.halted:
        return RiskDecision(False, REASON_HALTED)
    if inp.paused:
        return RiskDecision(False, REASON_PAUSED)
    if (
        inp.last_market_ms is None
        or inp.now_ms - inp.last_market_ms > inp.stale_data_seconds * 1000
    ):
        return RiskDecision(False, REASON_STALE)
    if inp.regime == "CRISIS":
        return RiskDecision(False, REASON_CRISIS)
    if inp.blackout_until_ms and inp.now_ms < inp.blackout_until_ms:
        return RiskDecision(False, REASON_BLACKOUT)
    if _is_short(req) and not inp.allow_short:
        return RiskDecision(False, REASON_SHORT_OFF)

    sized = plan(req, inp)
    if not sized.ok:
        return sized

    if inp.orders_today >= inp.max_orders_per_day:
        return RiskDecision(False, REASON_MAX_ORDERS)
    if any(p.symbol == req.symbol for p in inp.open_positions):
        return RiskDecision(False, REASON_ALREADY_OPEN)
    if len(inp.open_positions) >= inp.max_positions:
        return RiskDecision(False, REASON_SLOT_GLOBAL)
    same_strategy = sum(1 for p in inp.open_positions if p.strategy_id == req.strategy_id)
    if same_strategy >= inp.max_positions_per_strategy:
        return RiskDecision(False, REASON_SLOT_STRATEGY)

    equity = max(inp.equity, 1e-9)
    if inp.day_pnl <= -inp.daily_loss_limit * equity:
        return RiskDecision(False, REASON_DAILY)
    if inp.week_pnl <= -inp.weekly_loss_limit * equity:
        return RiskDecision(False, REASON_WEEKLY)
    if inp.dd_pct >= inp.max_drawdown:
        return RiskDecision(False, REASON_DD)

    open_risk = sum(p.risk_usd for p in inp.open_positions)
    if open_risk + sized.risk_usd > inp.portfolio_risk_max * equity + 1e-9:
        return RiskDecision(False, REASON_PORTFOLIO)

    # Fail-closed: nhom "" (chua biet) coi nhu cung mot nhom.
    group = req.group or ""
    group_risk = sum(p.risk_usd for p in inp.open_positions if (p.group or "") == group)
    if group_risk + sized.risk_usd > inp.max_correlated_risk * equity + 1e-9:
        return RiskDecision(False, REASON_CORRELATED)

    open_margin = sum(p.qty * p.entry / max(1, inp.leverage) for p in inp.open_positions)
    if open_margin + sized.margin > inp.margin_usage_max * equity + 1e-9:
        return RiskDecision(False, REASON_MARGIN)
    if sized.margin > inp.available_balance:
        return RiskDecision(False, REASON_MARGIN)

    return sized
