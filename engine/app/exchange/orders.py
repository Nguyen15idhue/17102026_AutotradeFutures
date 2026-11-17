"""Order state machine + idempotent clientOrderId.

Dinh dang: {strategy}-{symbol}-{ts}-{nonce}. Gui lai cung id khong tao lenh trung:
neu DB da co client_id -> tra ve ban ghi cu, khong goi REST."""

from __future__ import annotations

import sqlite3
import time
import uuid

from ..ops.log import log
from .rest import RestError

STATUSES = (
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
    "REJECTED",
    "TRIGGERED",
    "FINISHED",
)

_COLS = "client_id,symbol,side,type,qty,price,status,created_ms,updated_ms"
_COLS_X = "client_id,exchange_id,symbol,side,type,qty,price,status,created_ms,updated_ms"


def new_client_id(strategy: str, symbol: str) -> str:
    ts = int(time.time() * 1000)
    nonce = uuid.uuid4().hex[:6]
    return "%s-%s-%d-%s" % (strategy, symbol, ts, nonce)


class OrderManager:
    def __init__(self, con: sqlite3.Connection, rest, strategy: str = "sys"):
        self._con = con
        self._rest = rest
        self._strategy = strategy

    # -- dat lenh ------------------------------------------------------------
    def place(
        self, symbol: str, side: str, otype: str, qty: str, price: str = "", client_id: str = ""
    ) -> dict:
        """Lenh thuong qua /fapi/v1/order."""
        return self._send(
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": otype,
                "quantity": qty,
                **({"price": price} if price else {}),
                "newClientOrderId": client_id or new_client_id(self._strategy, symbol),
            },
        )

    def place_algo(
        self,
        symbol: str,
        side: str,
        otype: str,
        trigger: str,
        close_position: bool = True,
        client_id: str = "",
    ) -> dict:
        """SL/TP/trailing qua /fapi/v1/algoOrder (KHONG qua /fapi/v1/order: -4120)."""
        cid = client_id or new_client_id(self._strategy, symbol)
        params = {
            "symbol": symbol,
            "side": side,
            "type": otype,
            "algoType": "CONDITIONAL",
            "triggerPrice": trigger,
            "closePosition": "true" if close_position else "false",
            "workingType": "MARK_PRICE",
            "clientAlgoId": cid,
        }
        return self._send(
            "/fapi/v1/algoOrder", params, id_key="clientAlgoId", resp_id="algoId", client_id=cid
        )

    def _send(
        self,
        path: str,
        params: dict,
        id_key: str = "newClientOrderId",
        resp_id: str = "orderId",
        client_id: str = "",
    ) -> dict:
        cid = client_id or params.get(id_key, "")
        row = self._con.execute(
            "SELECT client_id,exchange_id,status FROM orders WHERE client_id=?", (cid,)
        ).fetchone()
        if row:  # idempotent: da co -> khong gui lai
            log("info", "order.dedup", client_id=cid)
            return {"client_id": row[0], "exchange_id": row[1], "status": row[2], "deduped": True}
        now = int(time.time() * 1000)
        try:
            res = self._rest.post(path, params)
        except RestError as e:
            if e.code == -2010:  # san bao trung id -> coi nhu da co
                log("warn", "order.dup_exchange", client_id=cid)
                return {"client_id": cid, "status": "UNKNOWN", "deduped": True}
            self._con.execute(
                "INSERT INTO orders(" + _COLS + ") VALUES(?,?,?,?,?,?, 'REJECTED',?,?)",
                (
                    cid,
                    params.get("symbol"),
                    params.get("side"),
                    params.get("type"),
                    params.get("quantity", ""),
                    params.get("price", ""),
                    now,
                    now,
                ),
            )
            raise
        self._con.execute(
            "INSERT INTO orders(" + _COLS_X + ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                str(res.get(resp_id, "")),
                params.get("symbol"),
                params.get("side"),
                params.get("type"),
                params.get("quantity", ""),
                params.get("price", ""),
                "NEW",
                now,
                now,
            ),
        )
        return {
            "client_id": cid,
            "exchange_id": str(res.get(resp_id, "")),
            "status": "NEW",
            "raw": res,
        }

    # -- cap nhat tu user stream ----------------------------------------------
    def on_order_trade(self, ev: dict) -> None:
        """ORDER_TRADE_UPDATE -> orders/fills/positions."""
        o = ev.get("o", {})
        cid = o.get("c", "")
        status = o.get("X", "")
        if not cid or status not in STATUSES:
            return
        now = int(time.time() * 1000)
        self._con.execute(
            "UPDATE orders SET status=?,exchange_id=?,updated_ms=? WHERE client_id=?",
            (status, str(o.get("i", "")), now, cid),
        )
        if o.get("s"):
            # incremental = max(l, z - da_ghi): live gui l>0 moi fill; mock don vao z.
            db_sum = (
                self._con.execute(
                    "SELECT COALESCE(SUM(CAST(qty AS REAL)),0) FROM fills WHERE order_ref=?", (cid,)
                ).fetchone()[0]
                or 0.0
            )
            try:
                z = float(o.get("z") or 0)
            except ValueError:
                z = 0.0
            inc = max(float(o.get("l") or 0), z - float(db_sum))
            if inc > 0:
                px = o.get("L") or o.get("ap") or "0"
                self._con.execute(
                    "INSERT INTO fills(order_ref,symbol,side,qty,price,fee,ts_ms)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (cid, o.get("s"), o.get("S"), str(inc), px, o.get("n", "0"), now),
                )
                # position local = cong don fill (khong tin truong p cua san)
                signed = inc if str(o.get("S", "")).upper() == "BUY" else -inc
                cur = self._con.execute(
                    "SELECT amt,entry FROM positions WHERE symbol=?", (o.get("s"),)
                ).fetchone()
                new_amt = float(cur[0]) + signed if cur else signed
                self._con.execute(
                    "INSERT INTO positions(symbol,amt,entry,updated_ms) VALUES(?,?,?,?) "
                    "ON CONFLICT(symbol) DO UPDATE SET amt=excluded.amt,"
                    "entry=excluded.entry,updated_ms=excluded.updated_ms",
                    (o.get("s"), str(new_amt), px or (cur[1] if cur else "0"), now),
                )

    def on_algo_update(self, ev: dict) -> None:
        """ALGO_UPDATE -> cap nhat status algo trong orders (clientAlgoId)."""
        a = ev.get("a", ev)
        cid = a.get("clientAlgoId") or a.get("c", "")
        status = a.get("algoStatus") or a.get("X", "")
        if not cid or status not in STATUSES:
            return
        now = int(time.time() * 1000)
        self._con.execute(
            "UPDATE orders SET status=?,updated_ms=? WHERE client_id=?", (status, now, cid)
        )
