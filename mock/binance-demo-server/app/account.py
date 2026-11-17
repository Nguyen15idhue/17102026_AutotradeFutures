"""Logic tai khoan: wallet, vi the, PnL, phi, lai lo, gia thanh ly.

Tier B: cong thuc thanh ly isolated bac 1, bo qua phi/funding.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import errors as E
from . import state
from .config import CFG
from .market import MARKET
from .num import dec, fmt
from .store import STORE

MMR_BTC = Decimal("0.004")
MMR_ALT = Decimal("0.01")


def mmr_of(symbol: str) -> Decimal:
    return MMR_BTC if symbol.upper().startswith("BTC") else MMR_ALT


def fee_rate(maker: bool) -> Decimal:
    bps = CFG.fee_maker_bps if maker else CFG.fee_taker_bps
    return Decimal(str(bps)) / Decimal("10000")


# ---------------------------------------------------------------- doc / ghi

def wallet() -> Decimal:
    return dec(STORE.account()["wallet_balance"])


def position_amt(symbol: str) -> Decimal:
    p = STORE.position(symbol.upper())
    return dec(p["position_amt"]) if p else Decimal("0")


def position_or_zero(symbol: str) -> dict[str, Any]:
    p = STORE.position(symbol.upper())
    if p:
        return p
    return {
        "symbol": symbol.upper(), "position_amt": "0", "entry_price": "0",
        "leverage": 3, "margin_type": "isolated", "isolated_wallet": "0",
        "realized_pnl": "0", "updated_ms": 0,
    }


def mark_price(symbol: str) -> Decimal:
    return dec(MARKET.premium_index(symbol)["markPrice"])


def unrealized(symbol: str) -> Decimal:
    p = position_or_zero(symbol)
    amt = dec(p["position_amt"])
    if amt == 0:
        return Decimal("0")
    return (mark_price(symbol) - dec(p["entry_price"])) * amt


def liquidation_price(p: dict[str, Any]) -> Decimal:
    amt = dec(p["position_amt"])
    entry = dec(p["entry_price"])
    if amt == 0 or entry == 0:
        return Decimal("0")
    lev = Decimal(int(p["leverage"]))
    m = mmr_of(p["symbol"])
    if amt > 0:
        return entry * (Decimal(1) - Decimal(1) / lev) / (Decimal(1) - m)
    return entry * (Decimal(1) + Decimal(1) / lev) / (Decimal(1) + m)


# ---------------------------------------------------------------- khop lenh

def apply_fill(symbol: str, side: str, qty: Decimal, price: Decimal, maker: bool) -> dict[str, Any]:
    """Cap nhat vi the + wallet + phi. Tra ve thong tin fill."""
    symbol = symbol.upper()
    p = position_or_zero(symbol)
    amt = dec(p["position_amt"])
    entry = dec(p["entry_price"])
    lev = int(p["leverage"])

    signed = qty if side.upper() == "BUY" else -qty
    realized = Decimal("0")

    if amt == 0 or (amt > 0) == (signed > 0):
        new_amt = amt + signed
        base = abs(amt) * entry + qty * price
        new_entry = (base / abs(new_amt)) if new_amt != 0 else Decimal("0")
    else:
        closed = min(abs(amt), qty)
        realized = (price - entry) * closed * (Decimal(1) if amt > 0 else Decimal(-1))
        new_amt = amt + signed
        if abs(signed) > abs(amt):
            new_entry = price
        else:
            new_entry = entry if new_amt != 0 else Decimal("0")

    quote = price * qty
    fee = quote * fee_rate(maker)
    new_wallet = wallet() + realized - fee
    isolated = (abs(new_amt) * new_entry / Decimal(lev)) if new_amt != 0 else Decimal("0")

    ts = state.now_ms()
    STORE.upsert_position({
        "symbol": symbol,
        "position_amt": str(new_amt),
        "entry_price": str(new_entry),
        "leverage": lev,
        "margin_type": p["margin_type"],
        "isolated_wallet": str(isolated),
        "realized_pnl": str(dec(p["realized_pnl"]) + realized),
        "updated_ms": ts,
    })
    STORE.set_wallet(new_wallet, ts)
    if realized != 0:
        STORE.insert_income(symbol, "REALIZED_PNL", realized, ts)
    STORE.insert_income(symbol, "COMMISSION", -fee, ts)

    return {
        "symbol": symbol, "side": side.upper(), "qty": qty, "price": price,
        "quote_qty": quote, "fee": fee, "realized": realized,
        "position_amt": new_amt, "entry_price": new_entry,
    }


def apply_funding(symbol: str, rate: Decimal) -> None:
    amt = position_amt(symbol)
    if amt == 0:
        return
    mark = mark_price(symbol)
    # funding duong: long tra, short nhan
    payment = -mark * amt * rate
    ts = state.now_ms()
    STORE.set_wallet(wallet() + payment, ts)
    STORE.insert_income(symbol, "FUNDING_FEE", payment, ts)


# ---------------------------------------------------------------- view

def _totals() -> tuple[Decimal, Decimal, Decimal]:
    """(initial_margin, unrealized, isolated_wallet)."""
    init = Decimal("0")
    upnl = Decimal("0")
    iso = Decimal("0")
    for p in STORE.positions():
        amt = dec(p["position_amt"])
        if amt == 0:
            continue
        init += abs(amt) * dec(p["entry_price"]) / Decimal(int(p["leverage"]))
        upnl += (mark_price(p["symbol"]) - dec(p["entry_price"])) * amt
        iso += dec(p["isolated_wallet"])
    return init, upnl, iso


def available() -> Decimal:
    init, upnl, _ = _totals()
    return max(Decimal("0"), wallet() + upnl - init)


def balance_view() -> list[dict[str, Any]]:
    w = wallet()
    avail = available()
    return [{
        "accountAlias": "mock",
        "asset": "USDT",
        "balance": fmt(w),
        "crossWalletBalance": fmt(w),
        "crossUnPnl": fmt(Decimal("0")),
        "availableBalance": fmt(avail),
        "maxWithdrawAmount": fmt(avail),
        "marginAvailable": True,
        "updateTime": state.now_ms(),
    }]


def account_view() -> dict[str, Any]:
    w = wallet()
    init, upnl, _ = _totals()
    avail = available()
    positions = []
    for p in STORE.positions():
        amt = dec(p["position_amt"])
        if amt == 0:
            continue
        positions.append({
            "symbol": p["symbol"],
            "positionAmt": str(amt),
            "entryPrice": fmt(dec(p["entry_price"])),
            "markPrice": fmt(mark_price(p["symbol"])),
            "unRealizedProfit": fmt((mark_price(p["symbol"]) - dec(p["entry_price"])) * amt),
            "liquidationPrice": fmt(liquidation_price(p)),
            "leverage": str(p["leverage"]),
            "marginType": p["margin_type"],
            "isolatedMargin": fmt(dec(p["isolated_wallet"])),
            "positionSide": "BOTH",
            "notional": fmt(abs(amt) * mark_price(p["symbol"])),
            "updateTime": p["updated_ms"],
        })
    return {
        "feeTier": 0,
        "canTrade": True,
        "canDeposit": True,
        "canWithdraw": False,
        "updateTime": state.now_ms(),
        "multiAssetsMargin": False,
        "totalInitialMargin": fmt(init),
        "totalMaintMargin": fmt(init * Decimal("0.4")),
        "totalWalletBalance": fmt(w),
        "totalUnrealizedProfit": fmt(upnl),
        "totalMarginBalance": fmt(w + upnl),
        "totalPositionInitialMargin": fmt(init),
        "totalOpenOrderInitialMargin": fmt(Decimal("0")),
        "totalCrossWalletBalance": fmt(Decimal("0")),
        "totalCrossUnPnl": fmt(Decimal("0")),
        "availableBalance": fmt(avail),
        "maxWithdrawAmount": fmt(avail),
        "assets": [{
            "asset": "USDT",
            "walletBalance": fmt(w),
            "unrealizedProfit": fmt(upnl),
            "marginBalance": fmt(w + upnl),
            "maintMargin": fmt(init * Decimal("0.4")),
            "initialMargin": fmt(init),
            "positionInitialMargin": fmt(init),
            "openOrderInitialMargin": fmt(Decimal("0")),
            "crossWalletBalance": fmt(Decimal("0")),
            "crossUnPnl": fmt(Decimal("0")),
            "availableBalance": fmt(avail),
            "maxWithdrawAmount": fmt(avail),
            "marginAvailable": True,
            "updateTime": state.now_ms(),
        }],
        "positions": positions,
    }


def position_risk_view() -> list[dict[str, Any]]:
    out = []
    for p in STORE.positions():
        amt = dec(p["position_amt"])
        mark = mark_price(p["symbol"]) if amt != 0 else Decimal("0")
        entry = dec(p["entry_price"])
        out.append({
            "symbol": p["symbol"],
            "positionAmt": str(amt),
            "entryPrice": str(entry),
            "markPrice": fmt(mark),
            "unRealizedProfit": fmt((mark - entry) * amt) if amt != 0 else "0.00000000",
            "liquidationPrice": fmt(liquidation_price(p)) if amt != 0 else "0",
            "leverage": str(p["leverage"]),
            "maxQty": "1000",
            "marginType": p["margin_type"],
            "isolatedMargin": fmt(dec(p["isolated_wallet"])),
            "isAutoAddMargin": "false",
            "positionSide": "BOTH",
            "notional": fmt(abs(amt) * mark),
            "isolatedWallet": fmt(dec(p["isolated_wallet"])),
            "updateTime": p["updated_ms"],
            "breakEvenPrice": fmt(entry),
        })
    return out


# ---------------------------------------------------------------- cau hinh

def set_leverage(symbol: str, leverage: int) -> dict[str, Any]:
    symbol = symbol.upper()
    MARKET.filters(symbol)
    if not 1 <= leverage <= CFG.max_leverage:
        raise E.err(E.INVALID_PARAM, p="leverage")
    p = position_or_zero(symbol)
    p["leverage"] = leverage
    amt = dec(p["position_amt"])
    p["isolated_wallet"] = str(abs(amt) * dec(p["entry_price"]) / Decimal(leverage)) if amt else "0"
    p["updated_ms"] = state.now_ms()
    STORE.upsert_position(p)
    return {"leverage": leverage, "maxNotionalValue": "50000"}


def set_margin_type(symbol: str, margin_type: str) -> dict[str, Any]:
    symbol = symbol.upper()
    MARKET.filters(symbol)
    mt = margin_type.upper()
    if mt not in ("ISOLATED", "CROSSED"):
        raise E.err(E.INVALID_PARAM, p="marginType")
    if position_amt(symbol) != 0:
        raise E.err(E.MARGIN_TYPE_HAS_POSITION)
    p = position_or_zero(symbol)
    p["margin_type"] = "isolated" if mt == "ISOLATED" else "cross"
    p["updated_ms"] = state.now_ms()
    STORE.upsert_position(p)
    return {"code": 200, "msg": "success"}
