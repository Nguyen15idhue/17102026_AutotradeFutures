"""Order engine: validate filter, khop lenh, cap nhat vi the + phi, phat event.

Tier B: khop toan bo (khong partial fill), matching theo top-of-book.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import account as A
from . import errors as E
from . import events, state
from .config import CFG
from .market import MARKET
from .num import dec, fmt, is_multiple, q_tick
from .store import STORE

CONDITIONAL_TYPES = {"STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"}
VALID_SIDES = {"BUY", "SELL"}
VALID_TYPES = {"LIMIT", "MARKET"}
VALID_TIF = {"GTC", "IOC", "FOK", "GTX", "GTD"}


class Engine:
    # ------------------------------------------------------------ validate

    def _params(self, p: dict[str, str]) -> dict[str, Any]:
        symbol = (p.get("symbol") or "").upper()
        if not symbol:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="symbol")
        MARKET.filters(symbol)

        side = (p.get("side") or "").upper()
        if not side:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="side")
        if side not in VALID_SIDES:
            raise E.err(E.INVALID_PARAM, p="side")

        otype = (p.get("type") or "").upper()
        if not otype:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="type")
        if otype in CONDITIONAL_TYPES:
            raise E.err(E.STOP_ORDER_SWITCH_ALGO)
        if otype not in VALID_TYPES:
            raise E.err(E.INVALID_PARAM, p="type")

        tif = (p.get("timeInForce") or ("GTC" if otype == "LIMIT" else "")).upper()
        if otype == "LIMIT":
            if tif not in VALID_TIF:
                raise E.err(E.INVALID_PARAM, p="timeInForce")

        qty_raw = p.get("quantity") or ""
        if not qty_raw:
            raise E.err(E.MANDATORY_PARAM_MISSING, p="quantity")
        qty = dec(qty_raw)
        if qty <= 0:
            raise E.err(E.QTY_FILTER_FAIL)

        f = MARKET.filters(symbol)
        if not is_multiple(qty, f["step"]):
            raise E.err(E.PRECISION_OVER_MAX)

        price = Decimal("0")
        if otype == "LIMIT":
            price_raw = p.get("price") or ""
            if not price_raw:
                raise E.err(E.MANDATORY_PARAM_MISSING, p="price")
            price = dec(price_raw)
            if price <= 0:
                raise E.err(E.INVALID_PARAM, p="price")
            if not is_multiple(price, f["tick"]):
                raise E.err(E.PRICE_FILTER_FAIL)
            price = q_tick(price, f["tick"])

        notional = qty * (price if price > 0 else MARKET.last_price(symbol))
        reduce_only = str(p.get("reduceOnly", "false")).lower() == "true"
        if notional < f["min_notional"] and not reduce_only:
            raise E.err(E.MIN_NOTIONAL_FAIL, n=fmt(f["min_notional"], 0))

        return {
            "symbol": symbol, "side": side, "type": otype, "tif": tif,
            "qty": qty, "price": price, "notional": notional,
            "reduce_only": reduce_only,
            "close_position": str(p.get("closePosition", "false")).lower() == "true",
            "working_type": (p.get("workingType") or "CONTRACT_PRICE").upper(),
            "price_protect": str(p.get("priceProtect", "false")).lower() == "true",
            "client_id": p.get("newClientOrderId") or "",
        }

    def _check_reduce_only(self, symbol: str, side: str) -> None:
        amt = A.position_amt(symbol)
        if amt == 0:
            raise E.err(E.REDUCE_ONLY_REJECT)
        if (amt > 0 and side == "BUY") or (amt < 0 and side == "SELL"):
            raise E.err(E.REDUCE_ONLY_REJECT)

    # ------------------------------------------------------------ place

    def place(self, p: dict[str, str], test_only: bool = False) -> dict[str, Any]:
        v = self._params(p)
        if v["close_position"]:
            raise E.err(E.UNSUPPORTED_PARAM, p="closePosition")

        if v["reduce_only"]:
            self._check_reduce_only(v["symbol"], v["side"])

        if v["type"] == "LIMIT" and v["tif"] == "GTX":
            bid, ask = MARKET.quote(v["symbol"])
            would_cross = ask <= v["price"] if v["side"] == "BUY" else bid >= v["price"]
            if would_cross:
                raise E.err(E.POST_ONLY_WOULD_TAKE)

        margin_need = v["notional"] / Decimal(3)
        if A.available() < margin_need:
            raise E.err(E.MARGIN_INSUFFICIENT)

        if test_only:
            return {}

        if v["client_id"] and STORE.order(client_id=v["client_id"]):
            raise E.BinanceError(-2010, "Duplicate order sent.")

        order_id = STORE.next_id("order_id", 3_000_000_000)
        ts = state.now_ms()
        order = {
            "order_id": order_id,
            "client_order_id": v["client_id"] or f"mock{order_id}",
            "symbol": v["symbol"],
            "side": v["side"],
            "type": v["type"],
            "orig_type": v["type"],
            "time_in_force": v["tif"] or None,
            "price": str(v["price"]),
            "stop_price": "0",
            "orig_qty": str(v["qty"]),
            "executed_qty": "0",
            "avg_price": "0",
            "status": "NEW",
            "reduce_only": int(v["reduce_only"]),
            "close_position": 0,
            "working_type": v["working_type"],
            "price_protect": int(v["price_protect"]),
            "created_ms": ts,
            "updated_ms": ts,
        }
        STORE.insert_order(order)
        events.publish("ORDER_TRADE_UPDATE", self._event(order, "NEW", "NEW"))

        bid, ask = MARKET.quote(v["symbol"])
        if v["type"] == "MARKET":
            self._execute(order, self._market_price(v["side"], bid, ask), maker=False)
        elif self._crosses(order, bid, ask):
            self._execute(order, self._cross_price(v["side"], bid, ask), maker=False)

        return self.view(STORE.order(order_id=order_id))

    # ------------------------------------------------------------ match

    def _slip(self, price: Decimal, side: str) -> Decimal:
        s = Decimal(str(CFG.slippage_bps)) / Decimal("10000")
        return price * (Decimal(1) + s) if side == "BUY" else price * (Decimal(1) - s)

    def _market_price(self, side: str, bid: Decimal, ask: Decimal) -> Decimal:
        return self._slip(ask if side == "BUY" else bid, side)

    def _crosses(self, order: dict, bid: Decimal, ask: Decimal) -> bool:
        price = dec(order["price"])
        return ask <= price if order["side"] == "BUY" else bid >= price

    def _cross_price(self, side: str, bid: Decimal, ask: Decimal) -> Decimal:
        return ask if side == "BUY" else bid

    def _execute(self, order: dict, price: Decimal, maker: bool) -> None:
        qty = dec(order["orig_qty"]) - dec(order["executed_qty"])
        if qty <= 0:
            return
        res = A.apply_fill(order["symbol"], order["side"], qty, price, maker)
        STORE.insert_fill({
            "order_id": order["order_id"], "symbol": order["symbol"],
            "side": order["side"], "price": str(price), "qty": str(qty),
            "quote_qty": str(res["quote_qty"]), "fee": str(res["fee"]),
            "fee_asset": "USDT", "maker": int(maker), "ts_ms": state.now_ms(),
        })
        avg = (dec(order["avg_price"]) * dec(order["executed_qty"]) + price * qty) / (
            dec(order["executed_qty"]) + qty)
        STORE.update_order(order["order_id"], executed_qty=str(qty), avg_price=str(avg),
                           status="FILLED", updated_ms=state.now_ms())
        updated = STORE.order(order_id=order["order_id"])
        event = self._event(updated, "TRADE" if maker else "TRADE", "FILLED")
        event["o"]["l"] = str(qty)
        event["o"]["z"] = str(qty)
        event["o"]["L"] = str(price)
        event["o"]["ap"] = fmt(avg)
        event["o"]["n"] = fmt(res["fee"])
        event["o"]["m"] = maker
        events.publish("ORDER_TRADE_UPDATE", event)
        events.publish("ACCOUNT_UPDATE", self._account_event(order["symbol"]))

    def tick(self) -> None:
        """Goi dinh ky: khop cac lenh LIMIT dang cho."""
        for o in STORE.orders(status="NEW"):
            if o["type"] != "LIMIT":
                continue
            bid, ask = MARKET.quote(o["symbol"])
            if CFG.fill_model == "optimistic":
                last = MARKET.last_price(o["symbol"])
                price = dec(o["price"])
                hit = last <= price if o["side"] == "BUY" else last >= price
            else:
                hit = self._crosses(o, bid, ask)
            if hit:
                self._execute(o, dec(o["price"]), maker=True)

    def market_close(self, symbol: str, side: str, qty: Decimal) -> dict:
        """Dong vi the bang market — bo qua kiem tra margin (dung cho SL/TP)."""
        order_id = STORE.next_id("order_id", 3_000_000_000)
        ts = state.now_ms()
        order = {
            "order_id": order_id,
            "client_order_id": f"close{order_id}",
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "orig_type": "MARKET",
            "time_in_force": None,
            "price": "0",
            "stop_price": "0",
            "orig_qty": str(qty),
            "executed_qty": "0",
            "avg_price": "0",
            "status": "NEW",
            "reduce_only": 1,
            "close_position": 1,
            "working_type": "CONTRACT_PRICE",
            "price_protect": 0,
            "created_ms": ts,
            "updated_ms": ts,
        }
        STORE.insert_order(order)
        bid, ask = MARKET.quote(symbol)
        self._execute(order, self._market_price(side, bid, ask), maker=False)
        return STORE.order(order_id=order_id)

    # ------------------------------------------------------------ view

    def view(self, o: dict) -> dict[str, Any]:
        return {
            "orderId": o["order_id"],
            "symbol": o["symbol"],
            "status": o["status"],
            "clientOrderId": o["client_order_id"],
            "price": fmt(dec(o["price"])),
            "avgPrice": fmt(dec(o["avg_price"])),
            "origQty": str(o["orig_qty"]),
            "executedQty": str(o["executed_qty"]),
            "cumQty": str(o["executed_qty"]),
            "cumQuote": fmt(dec(o["executed_qty"]) * dec(o["avg_price"])),
            "timeInForce": o["time_in_force"] or "GTC",
            "type": o["type"],
            "reduceOnly": bool(o["reduce_only"]),
            "closePosition": bool(o["close_position"]),
            "side": o["side"],
            "positionSide": "BOTH",
            "stopPrice": o["stop_price"],
            "workingType": o["working_type"],
            "priceProtect": bool(o["price_protect"]),
            "origType": o["orig_type"],
            "priceMatch": "NONE",
            "selfTradePreventionMode": "NONE",
            "goodTillDate": 0,
            "time": o["created_ms"],
            "updateTime": o["updated_ms"],
        }

    def _event(self, o: dict, exec_type: str, status: str) -> dict:
        return {
            "e": "ORDER_TRADE_UPDATE",
            "T": state.now_ms(),
            "E": state.now_ms(),
            "o": {
                "s": o["symbol"], "c": o["client_order_id"], "S": o["side"],
                "o": o["type"], "f": o["time_in_force"] or "GTC",
                "q": o["orig_qty"], "p": o["price"], "ap": fmt(dec(o["avg_price"])),
                "sp": o["stop_price"], "x": exec_type, "X": status,
                "i": o["order_id"], "l": "0", "z": o["executed_qty"], "L": "0",
                "n": "0", "N": "USDT", "T": o["updated_ms"], "t": 0,
                "b": "0", "a": "0", "m": False, "R": bool(o["reduce_only"]),
                "wt": o["working_type"], "ot": o["orig_type"], "ps": "BOTH",
                "cp": bool(o["close_position"]), "AP": "0", "cr": "0", "rp": "0",
                "pP": bool(o["price_protect"]), "si": 0, "ss": 0, "V": "NONE",
                "pm": "NONE", "gtd": 0,
            },
        }

    def _account_event(self, symbol: str) -> dict:
        p = A.position_or_zero(symbol)
        return {
            "e": "ACCOUNT_UPDATE",
            "T": state.now_ms(),
            "E": state.now_ms(),
            "a": {
                "m": "ORDER",
                "B": [{"a": "USDT", "wb": fmt(A.wallet()), "cw": "0", "bc": "0"}],
                "P": [{
                    "s": symbol,
                    "pa": p["position_amt"],
                    "ep": p["entry_price"],
                    "up": fmt(A.unrealized(symbol)),
                    "mt": p["margin_type"],
                    "iw": p["isolated_wallet"],
                    "ps": "BOTH",
                }],
            },
        }

    # ------------------------------------------------------------ cancel / query

    def cancel(self, symbol: str, order_id: int | None, client_id: str | None) -> dict:
        symbol = symbol.upper()
        MARKET.filters(symbol)
        o = STORE.order(order_id=order_id, client_id=client_id)
        if not o or o["symbol"] != symbol or o["status"] not in ("NEW", "PARTIALLY_FILLED"):
            raise E.err(E.CANCEL_REJECTED)
        STORE.update_order(o["order_id"], status="CANCELED", updated_ms=state.now_ms())
        updated = STORE.order(order_id=o["order_id"])
        events.publish("ORDER_TRADE_UPDATE", self._event(updated, "CANCELED", "CANCELED"))
        return self.view(updated)

    def get(self, symbol: str, order_id: int | None, client_id: str | None) -> dict:
        symbol = symbol.upper()
        o = STORE.order(order_id=order_id, client_id=client_id)
        if not o or o["symbol"] != symbol:
            raise E.err(E.ORDER_NOT_FOUND)
        return self.view(o)

    def cancel_all(self, symbol: str) -> dict:
        symbol = symbol.upper()
        MARKET.filters(symbol)
        n = 0
        for o in STORE.orders(symbol=symbol, status="NEW"):
            STORE.update_order(o["order_id"], status="CANCELED", updated_ms=state.now_ms())
            n += 1
        return {"code": 200, "msg": "success", "count": n}


ENGINE = Engine()
