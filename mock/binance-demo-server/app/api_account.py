"""Endpoint account (SIGNED)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from . import account as A
from . import errors as E
from . import state
from .auth import signed_params
from .market import MARKET
from .num import fmt
from .store import STORE

router = APIRouter()

_MAKER = "0.000200"
_TAKER = "0.000500"


def _symbol(p: dict) -> str:
    s = p.get("symbol", "")
    if not s:
        raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
    return s.upper()


@router.get("/fapi/v1/commissionRate")
async def commission_rate(p: dict = Depends(signed_params)) -> dict:
    return {"symbol": _symbol(p), "makerCommissionRate": _MAKER, "takerCommissionRate": _TAKER}


@router.get("/fapi/v2/balance")
async def balance(p: dict = Depends(signed_params)) -> list:
    return A.balance_view()


@router.get("/fapi/v2/account")
async def account(p: dict = Depends(signed_params)) -> dict:
    return A.account_view()


@router.get("/fapi/v2/positionRisk")
async def position_risk(p: dict = Depends(signed_params)) -> list:
    return A.position_risk_view()


@router.get("/fapi/v1/leverageBracket")
async def leverage_bracket(p: dict = Depends(signed_params)) -> list:
    syms = [_symbol(p)] if p.get("symbol") else list(MARKET.symbols())
    out = []
    for s in syms:
        m = A.mmr_of(s)
        out.append({
            "symbol": s,
            "brackets": [{
                "bracket": 1,
                "initialLeverage": 125,
                "notionalCap": 50000,
                "notionalFloor": 0,
                "maintMarginRatio": float(m),
                "cum": 0.0,
            }],
        })
    return out


@router.get("/fapi/v1/income")
async def income(p: dict = Depends(signed_params),
                 limit: int = Query(100, ge=1, le=1000)) -> list:
    rows = STORE.incomes(limit)
    out = []
    for r in rows:
        if p.get("incomeType") and r["income_type"] != p["incomeType"]:
            continue
        out.append({
            "symbol": r["symbol"] or "",
            "incomeType": r["income_type"],
            "income": r["income"],
            "asset": r["asset"],
            "info": "",
            "time": r["ts_ms"],
            "tranId": r["id"],
            "tradeId": str(r["id"]),
        })
    return out


@router.get("/fapi/v1/userTrades")
async def user_trades(p: dict = Depends(signed_params),
                      limit: int = Query(100, ge=1, le=1000)) -> list:
    rows = STORE.fills(_symbol(p) if p.get("symbol") else None, limit)
    return [{
        "symbol": r["symbol"],
        "id": r["trade_id"],
        "orderId": r["order_id"],
        "side": r["side"],
        "price": r["price"],
        "qty": r["qty"],
        "quoteQty": r["quote_qty"],
        "realizedPnl": "0",
        "commission": r["fee"],
        "commissionAsset": r["fee_asset"],
        "time": r["ts_ms"],
        "maker": bool(r["maker"]),
        "buyer": r["side"] == "BUY",
    } for r in rows]


@router.post("/fapi/v1/leverage")
async def set_leverage(p: dict = Depends(signed_params)) -> dict:
    try:
        lev = int(p.get("leverage", "0"))
    except ValueError:
        raise E.err(E.INVALID_PARAM, p="leverage") from None
    return A.set_leverage(_symbol(p), lev)


@router.post("/fapi/v1/marginType")
async def set_margin_type(p: dict = Depends(signed_params)) -> dict:
    return A.set_margin_type(_symbol(p), p.get("marginType", ""))


@router.get("/_debug/account")
async def debug_account() -> dict:
    return {
        "time": state.now_ms(),
        "wallet": fmt(A.wallet()),
        "available": fmt(A.available()),
        "positions": A.position_risk_view(),
        "orders": [{
            "id": o["order_id"], "symbol": o["symbol"], "side": o["side"],
            "type": o["type"], "qty": o["orig_qty"], "price": o["price"],
            "status": o["status"],
        } for o in STORE.orders(status="NEW")],
        "algo_orders": [{
            "id": a["algo_id"], "symbol": a["symbol"], "side": a["side"],
            "type": a["type"], "trigger": a["trigger_price"], "status": a["status"],
        } for a in STORE.algos(status="NEW")],
        "events": STORE.events(10),
    }
