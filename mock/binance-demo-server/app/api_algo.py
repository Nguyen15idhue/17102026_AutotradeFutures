"""Endpoint Algo Order (SIGNED) — STOP / TAKE_PROFIT."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from . import errors as E
from .algo import ALGO
from .auth import signed_params
from .market import MARKET

router = APIRouter()


def _int_or_none(p: dict, key: str) -> int | None:
    v = p.get(key)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except ValueError:
        raise E.err(E.INVALID_PARAM, p=key) from None


@router.post("/fapi/v1/algoOrder")
async def new_algo_order(p: dict = Depends(signed_params)) -> dict:
    return ALGO.place(p)


@router.get("/fapi/v1/algoOrder")
async def query_algo_order(p: dict = Depends(signed_params)) -> dict:
    return ALGO.get(_int_or_none(p, "algoId"), p.get("clientAlgoId"))


@router.delete("/fapi/v1/algoOrder")
async def cancel_algo_order(p: dict = Depends(signed_params)) -> dict:
    return ALGO.cancel(_int_or_none(p, "algoId"), p.get("clientAlgoId"))


@router.delete("/fapi/v1/algoOpenOrders")
async def cancel_all_algo(p: dict = Depends(signed_params)) -> dict:
    symbol = (p.get("symbol") or "").upper()
    if not symbol:
        raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
    MARKET.filters(symbol)
    return ALGO.cancel_all(symbol)


@router.get("/fapi/v1/openAlgoOrders")
async def open_algo_orders(p: dict = Depends(signed_params)) -> dict:
    symbol = p.get("symbol")
    if symbol:
        MARKET.filters(symbol.upper())
    return ALGO.open_orders(symbol)


@router.get("/fapi/v1/historicalAlgoOrders")
async def historical_algo_orders(p: dict = Depends(signed_params),
                                 limit: int = Query(100, ge=1, le=1000)) -> dict:
    symbol = p.get("symbol")
    if symbol:
        MARKET.filters(symbol.upper())
    return ALGO.history(symbol, limit)
