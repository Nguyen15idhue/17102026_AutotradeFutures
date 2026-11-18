"""Sizing P1.3: risk$ -> qty, floor theo step/tick, reject khi duoi minNotional.

Vi sao floor ma khong round: lam tron len lam risk thuc te > risk khai bao —
dung thu ma AGENTS §3.2 cam. Duoi minNotional thi HUY, khong tang size de bu.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from .types import OrderRequest, RiskDecision, RiskInputs

REASON_INVALID_STOP = "invalid_stop"
REASON_MIN_NOTIONAL = "min_notional"
REASON_RISK_TOO_LARGE = "risk_too_large"


def floor_to(value: float, step: float) -> float:
    """Floor ve boi so cua step (Decimal de tranh sai so float)."""
    if step <= 0:
        return value
    d = Decimal(str(value))
    s = Decimal(str(step))
    return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)


def plan(req: OrderRequest, inp: RiskInputs) -> RiskDecision:
    """Tinh qty/notional/margin. Tra ve ok=False neu stop sai phia hoac duoi min."""
    if req.entry <= 0 or req.stop <= 0:
        return RiskDecision(False, REASON_INVALID_STOP)
    is_long = req.side.upper() == "BUY"
    if is_long and req.stop >= req.entry:
        return RiskDecision(False, REASON_INVALID_STOP)
    if not is_long and req.stop <= req.entry:
        return RiskDecision(False, REASON_INVALID_STOP)
    if req.tp is not None:
        if is_long and req.tp <= req.entry:
            return RiskDecision(False, REASON_INVALID_STOP)
        if not is_long and req.tp >= req.entry:
            return RiskDecision(False, REASON_INVALID_STOP)

    max_risk = inp.risk_per_trade * inp.equity
    # risk_usd co the do caller dat (CLI tay) nhung khong duoc vuot risk/lanh
    risk_usd = float(req.meta.get("risk_usd") or max_risk)
    if risk_usd <= 0 or risk_usd > max_risk * (1 + 1e-9):
        return RiskDecision(False, REASON_RISK_TOO_LARGE)
    stop_distance = abs(req.entry - req.stop)
    qty = floor_to(risk_usd / stop_distance, inp.step_size)
    if qty <= 0:
        return RiskDecision(False, REASON_MIN_NOTIONAL)
    notional = qty * req.entry
    if notional < inp.min_notional:
        return RiskDecision(False, REASON_MIN_NOTIONAL)
    margin = notional / max(1, inp.leverage)
    real_risk = qty * stop_distance
    # Guard: sau floor, risk thuc te khong duoc vuot risk da dat
    if real_risk > risk_usd * (1 + 1e-9):
        return RiskDecision(False, REASON_RISK_TOO_LARGE)
    return RiskDecision(True, "", qty=qty, notional=notional, margin=margin, risk_usd=real_risk)


def round_price(price: float, tick: float) -> float:
    """Floor gia ve tick — de gia gui san khop exchangeInfo, khong bi -4014."""
    return floor_to(price, tick)
