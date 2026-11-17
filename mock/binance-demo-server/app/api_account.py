"""Endpoint account. M0.3: chi commissionRate (dung de test duong SIGNED)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import signed_params
from .errors import INVALID_SYMBOL, err

router = APIRouter()

# Gia tri thuc do tren live 17/11/2026 (docs/verification.md)
_MAKER = "0.000200"
_TAKER = "0.000500"


@router.get("/fapi/v1/commissionRate")
async def commission_rate(p: dict = Depends(signed_params)) -> dict:
    symbol = p.get("symbol", "")
    if not symbol:
        raise err(INVALID_SYMBOL)
    return {"symbol": symbol.upper(), "makerCommissionRate": _MAKER, "takerCommissionRate": _TAKER}
