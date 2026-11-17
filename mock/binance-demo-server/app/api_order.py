"""Endpoint trade: order CRUD (SIGNED). Lenh dieu kien -> -4120."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from . import errors as E
from .auth import signed_params
from .market import MARKET
from .orders import ENGINE
from .store import STORE

router = APIRouter()


def _symbol(p: dict) -> str:
    s = (p.get("symbol") or "").upper()
    if not s:
        raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
    MARKET.filters(s)
    return s


def _int_or_none(p: dict, key: str) -> int | None:
    v = p.get(key)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except ValueError:
        raise E.err(E.INVALID_PARAM, p=key) from None


@router.post("/fapi/v1/order")
async def new_order(p: dict = Depends(signed_params)) -> dict:
    return ENGINE.place(p)


@router.post("/fapi/v1/order/test")
async def test_order(p: dict = Depends(signed_params)) -> dict:
    return ENGINE.place(p, test_only=True)


@router.get("/fapi/v1/order")
async def query_order(p: dict = Depends(signed_params)) -> dict:
    return ENGINE.get(_symbol(p), _int_or_none(p, "orderId"), p.get("origClientOrderId"))


@router.delete("/fapi/v1/order")
async def cancel_order(p: dict = Depends(signed_params)) -> dict:
    return ENGINE.cancel(_symbol(p), _int_or_none(p, "orderId"), p.get("origClientOrderId"))


@router.delete("/fapi/v1/allOpenOrders")
async def cancel_all(p: dict = Depends(signed_params)) -> dict:
    return ENGINE.cancel_all(_symbol(p))


@router.get("/fapi/v1/openOrders")
async def open_orders(p: dict = Depends(signed_params)) -> list:
    symbol = p.get("symbol")
    if symbol:
        symbol = _symbol(p)
    return [ENGINE.view(o) for o in STORE.orders(symbol=symbol, status="NEW")]


@router.get("/fapi/v1/allOrders")
async def all_orders(p: dict = Depends(signed_params),
                     limit: int = Query(500, ge=1, le=1000)) -> list:
    symbol = _symbol(p) if p.get("symbol") else None
    return [ENGINE.view(o) for o in STORE.orders(symbol=symbol)[:limit]]
