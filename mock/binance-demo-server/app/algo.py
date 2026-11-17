"""Algo engine: STOP / TAKE_PROFIT / TRAILING (conditional orders).

Vong doi: NEW -> TRIGGERING -> TRIGGERED -> FINISHED
          + CANCELED / REJECTED / EXPIRED (khi position ve 0)
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from . import account as A
from . import errors as E
from . import events, state
from .market import MARKET
from .num import dec, fmt, is_multiple
from .orders import ENGINE
from .store import STORE

COND = {"STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"}
ALGO_ID_RE = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")


class AlgoEngine:
    # ------------------------------------------------------------ validate

    def _validate(self, p: dict[str, str]) -> dict[str, Any]:
        at = (p.get("algoType") or "").upper()
        if at != "CONDITIONAL":
            raise E.err(E.INVALID_PARAM, p="algoType")

        otype = (p.get("type") or "").upper()
        if otype not in COND:
            raise E.err(E.INVALID_PARAM, p="type")

        symbol = (p.get("symbol") or "").upper()
        if not symbol:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
        f = MARKET.filters(symbol)

        side = (p.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            raise E.err(E.INVALID_PARAM, p="side")

        trig_raw = p.get("triggerPrice") or ""
        if not trig_raw:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="triggerPrice")
        trigger = dec(trig_raw)
        if not is_multiple(trigger, f["tick"]):
            raise E.err(E.PRICE_FILTER_FAIL)

        close_pos = str(p.get("closePosition", "false")).lower() == "true"
        qty_raw = p.get("quantity") or ""
        reduce_only = str(p.get("reduceOnly", "false")).lower() == "true"

        if close_pos:
            if qty_raw:
                raise E.err(E.CLOSE_POSITION_WITH_QTY)
            if reduce_only:
                raise E.err(E.CLOSE_POSITION_WITH_QTY)
            qty = Decimal("0")
        else:
            if not qty_raw:
                raise E.err(E.MANDATORY_PARAM_MISSING, p="quantity")
            qty = dec(qty_raw)
            if qty <= 0:
                raise E.err(E.QTY_FILTER_FAIL)
            if not is_multiple(qty, f["step"]):
                raise E.err(E.PRECISION_OVER_MAX)

        client_id = p.get("clientAlgoId") or ""
        if client_id and not ALGO_ID_RE.match(client_id):
            raise E.err(E.INVALID_PARAM, p="clientAlgoId")

        working = (p.get("workingType") or "CONTRACT_PRICE").upper()
        if working not in ("MARK_PRICE", "CONTRACT_PRICE"):
            raise E.err(E.INVALID_PARAM, p="workingType")

        self._check_immediate(otype, side, trigger, working, symbol)

        return {
            "symbol": symbol, "side": side, "type": otype, "algo_type": at,
            "trigger": trigger, "working": working,
            "close_position": close_pos, "reduce_only": reduce_only, "qty": qty,
            "price_protect": str(p.get("priceProtect", "false")).lower() == "true",
            "client_id": client_id,
        }

    def _price_for(self, working: str, symbol: str) -> Decimal:
        if working == "MARK_PRICE":
            return dec(MARKET.premium_index(symbol)["markPrice"])
        return MARKET.last_price(symbol)

    def _triggered(self, otype: str, side: str, trigger: Decimal, price: Decimal) -> bool:
        if otype in ("STOP", "STOP_MARKET"):
            return price >= trigger if side == "BUY" else price <= trigger
        if otype in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
            return price <= trigger if side == "BUY" else price >= trigger
        return False  # TRAILING chua ho tro (Tier C)

    def _check_immediate(self, otype: str, side: str, trigger: Decimal,
                         working: str, symbol: str) -> None:
        if otype == "TRAILING_STOP_MARKET":
            return
        price = self._price_for(working, symbol)
        if self._triggered(otype, side, trigger, price):
            raise E.err(E.WOULD_IMMEDIATELY_TRIGGER)

    # ------------------------------------------------------------ place

    def place(self, p: dict[str, str]) -> dict[str, Any]:
        v = self._validate(p)
        if v["client_id"] and STORE.algo(client_id=v["client_id"]):
            raise E.BinanceError(-2010, "Duplicate clientAlgoId.")

        algo_id = STORE.next_id("algo_id", 2_000_000)
        ts = state.now_ms()
        algo = {
            "algo_id": algo_id,
            "client_algo_id": v["client_id"] or f"mock{algo_id}",
            "symbol": v["symbol"],
            "side": v["side"],
            "type": v["type"],
            "algo_type": v["algo_type"],
            "trigger_price": str(v["trigger"]),
            "working_type": v["working"],
            "price_protect": int(v["price_protect"]),
            "close_position": int(v["close_position"]),
            "reduce_only": int(v["reduce_only"]),
            "quantity": str(v["qty"]),
            "status": "NEW",
            "order_id": None,
            "created_ms": ts,
            "updated_ms": ts,
            "trigger_ms": 0,
        }
        STORE.insert_algo(algo)
        events.publish("ALGO_UPDATE", self._event(algo))
        return self.view(algo)

    # ------------------------------------------------------------ tick

    def tick(self) -> None:
        for a in STORE.algos(status="NEW"):
            symbol = a["symbol"]
            amt = A.position_amt(symbol)
            if amt == 0:
                self._set_status(a, "EXPIRED")
                continue
            if a["type"] == "TRAILING_STOP_MARKET":
                continue
            price = self._price_for(a["working_type"], symbol)
            if not self._triggered(a["type"], a["side"], dec(a["trigger_price"]), price):
                continue
            if a["price_protect"] and not self._price_protect_ok(symbol):
                continue
            self._fire(a, amt)

    def _price_protect_ok(self, symbol: str) -> bool:
        mark = dec(MARKET.premium_index(symbol)["markPrice"])
        last = MARKET.last_price(symbol)
        if last == 0:
            return True
        protect = MARKET.filters(symbol)["trigger_protect"]
        return abs(mark - last) / last <= protect

    def _fire(self, a: dict, amt: Decimal) -> None:
        self._set_status(a, "TRIGGERING")
        qty = abs(amt) if a["close_position"] else min(dec(a["quantity"]), abs(amt))
        if qty <= 0:
            self._set_status(a, "EXPIRED")
            return
        order = ENGINE.market_close(a["symbol"], a["side"], qty)
        self._set_status(a, "TRIGGERED", order_id=order["order_id"])
        self._set_status(a, "FINISHED", order_id=order["order_id"])

    # ------------------------------------------------------------ state

    def _set_status(self, a: dict, status: str, order_id: int | None = None) -> None:
        fields: dict[str, Any] = {"status": status, "updated_ms": state.now_ms()}
        if order_id is not None:
            fields["order_id"] = order_id
        if status == "TRIGGERED":
            fields["trigger_ms"] = state.now_ms()
        STORE.update_algo(a["algo_id"], **fields)
        updated = STORE.algo(algo_id=a["algo_id"])
        a.update(updated)
        events.publish("ALGO_UPDATE", self._event(updated))

    # ------------------------------------------------------------ view

    def view(self, a: dict) -> dict[str, Any]:
        return {
            "algoId": a["algo_id"],
            "clientAlgoId": a["client_algo_id"],
            "algoType": a["algo_type"],
            "orderType": a["type"],
            "symbol": a["symbol"],
            "side": a["side"],
            "positionSide": "BOTH",
            "timeInForce": "GTC",
            "quantity": a["quantity"],
            "algoStatus": a["status"],
            "triggerPrice": fmt(dec(a["trigger_price"])),
            "price": "0",
            "icebergQuantity": None,
            "selfTradePreventionMode": "NONE",
            "workingType": a["working_type"],
            "priceMatch": "NONE",
            "closePosition": bool(a["close_position"]),
            "priceProtect": bool(a["price_protect"]),
            "reduceOnly": bool(a["reduce_only"]),
            "activatePrice": "",
            "callbackRate": "",
            "createTime": a["created_ms"],
            "updateTime": a["updated_ms"],
            "triggerTime": a["trigger_ms"],
            "goodTillDate": 0,
        }

    def _event(self, a: dict) -> dict:
        return {
            "e": "ALGO_UPDATE",
            "T": state.now_ms(),
            "E": state.now_ms(),
            "o": {
                "caid": a["client_algo_id"], "aid": a["algo_id"], "at": a["algo_type"],
                "o": a["type"], "s": a["symbol"], "S": a["side"], "ps": "BOTH",
                "f": "GTC", "q": a["quantity"], "X": a["status"],
                "ai": str(a["order_id"] or ""), "ap": "0.00000", "aq": "0.00000",
                "act": "0", "tp": fmt(dec(a["trigger_price"])), "p": "0",
                "V": "NONE", "wt": a["working_type"], "pm": "NONE",
                "cp": bool(a["close_position"]), "pP": bool(a["price_protect"]),
                "R": bool(a["reduce_only"]), "tt": a["trigger_ms"], "gtd": 0,
                "rm": "", "ia": False,
            },
        }

    # ------------------------------------------------------------ query / cancel

    def get(self, algo_id: int | None, client_id: str | None) -> dict:
        a = STORE.algo(algo_id=algo_id, client_id=client_id)
        if not a:
            raise E.err(E.ALGO_NOT_FOUND)
        return self.view(a)

    def cancel(self, algo_id: int | None, client_id: str | None) -> dict:
        a = STORE.algo(algo_id=algo_id, client_id=client_id)
        if not a or a["status"] != "NEW":
            raise E.err(E.CANCEL_REJECTED)
        self._set_status(a, "CANCELED")
        return self.view(STORE.algo(algo_id=a["algo_id"]))

    def cancel_all(self, symbol: str) -> dict:
        symbol = symbol.upper()
        MARKET.filters(symbol)
        n = 0
        for a in STORE.algos(symbol=symbol, status="NEW"):
            self._set_status(a, "CANCELED")
            n += 1
        return {"code": 200, "msg": "success", "count": n}

    def open_orders(self, symbol: str | None = None) -> dict:
        items = STORE.algos(symbol=symbol.upper() if symbol else None, status="NEW")
        return {"total": len(items), "orders": [self.view(a) for a in items]}

    def history(self, symbol: str | None = None, limit: int = 100) -> dict:
        items = STORE.algos(symbol=symbol.upper() if symbol else None)[:limit]
        return {"total": len(items), "orders": [self.view(a) for a in items]}


ALGO = AlgoEngine()
