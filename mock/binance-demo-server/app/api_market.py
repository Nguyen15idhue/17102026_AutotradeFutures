"""Endpoint du lieu thi truong (security = NONE)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from . import errors as E
from . import state
from .market import MARKET

router = APIRouter()


@router.get("/fapi/v1/exchangeInfo")
async def exchange_info(symbol: str | None = None) -> dict:
    body = MARKET.raw_exchange_info(symbol)
    body.update({
        "timezone": "UTC",
        "serverTime": state.now_ms(),
        "rateLimits": [
            {"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "intervalNum": 1, "limit": 2400},
            {"rateLimitType": "ORDERS", "interval": "SECOND", "intervalNum": 10, "limit": 300},
            {"rateLimitType": "ORDERS", "interval": "MINUTE", "intervalNum": 1, "limit": 1200},
        ],
        "exchangeFilters": [],
    })
    return body


def _need_symbol(symbol: str | None) -> str:
    if not symbol:
        raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
    return symbol.upper()


@router.get("/fapi/v1/klines")
async def klines(symbol: str | None = None, interval: str = "1m",
                 limit: int = Query(500, ge=1, le=1500)) -> list:
    s = _need_symbol(symbol)
    return MARKET.klines(s, interval, limit)


@router.get("/fapi/v1/ticker/price")
async def ticker_price(symbol: str | None = None) -> dict | list:
    if symbol:
        s = symbol.upper()
        return {"symbol": s, "price": f"{MARKET.last_price(s):.8f}", "time": state.now_ms()}
    return [
        {"symbol": x, "price": f"{MARKET.last_price(x):.8f}", "time": state.now_ms()}
        for x in MARKET.symbols()
    ]


@router.get("/fapi/v1/ticker/bookTicker")
async def book_ticker(symbol: str | None = None) -> dict | list:
    if symbol:
        return MARKET.book_ticker(symbol)
    return [MARKET.book_ticker(x) for x in MARKET.symbols()]


@router.get("/fapi/v1/premiumIndex")
async def premium_index(symbol: str | None = None) -> dict | list:
    if symbol:
        return MARKET.premium_index(symbol)
    return [MARKET.premium_index(x) for x in MARKET.symbols()]


@router.get("/fapi/v1/fundingRate")
async def funding_rate(symbol: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> list:
    return MARKET.funding_rate(_need_symbol(symbol), limit)


@router.get("/fapi/v1/openInterest")
async def open_interest(symbol: str | None = None) -> dict:
    return MARKET.open_interest(_need_symbol(symbol))
