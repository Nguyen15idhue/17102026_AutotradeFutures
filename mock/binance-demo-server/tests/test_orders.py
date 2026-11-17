"""M0.6 â€” order engine: validate filter, khop, phi, vi the, huy, idempotency."""
from __future__ import annotations

from decimal import Decimal

from app import account as A
from app.market import MARKET
from app.orders import ENGINE
from app.store import STORE
from tests.test_auth import signed_delete, signed_get, signed_post


def place(**kw):
    body = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"}
    body.update({k: str(v) for k, v in kw.items()})
    return signed_post("/fapi/v1/order", body)


def far_limit(side: str = "BUY", price: str | None = None, qty: str = "0.002") -> str:
    """Gia cach xa de khong khop ngay."""
    mart = MARKET.last_price("BTCUSDT")
    p = price or (str((mart * Decimal("0.5")).quantize(Decimal("0.1"))) if side == "BUY"
                  else str((mart * Decimal("1.5")).quantize(Decimal("0.1"))))
    return p


def test_market_buy_fills_and_moves_position():
    r = place()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FILLED"
    assert Decimal(body["executedQty"]) == Decimal("0.002")
    assert A.position_amt("BTCUSDT") > 0
    assert body["avgPrice"] != "0.00000000"


def test_market_sell_short():
    r = place(side="SELL")
    assert r.json()["status"] == "FILLED"
    assert A.position_amt("BTCUSDT") < 0


def test_limit_rests_then_fills_on_tick():
    p = far_limit("BUY")
    r = place(type="LIMIT", price=p, timeInForce="GTC")
    body = r.json()
    assert body["status"] == "NEW"
    assert len(signed_get("/fapi/v1/openOrders").json()) == 1

    # ep gia cham lenh: dat ask xuong duoi gia limit
    orig = MARKET.quote
    try:
        MARKET.quote = lambda s: (Decimal(p) - Decimal("10"), Decimal(p) - Decimal("5"))
        ENGINE.tick()
    finally:
        MARKET.quote = orig
    assert STORE.order(order_id=body["orderId"])["status"] == "FILLED"


def test_gtx_rejects_when_would_cross():
    bid, ask = MARKET.quote("BTCUSDT")
    r = place(type="LIMIT", price=str(ask), timeInForce="GTX")
    assert r.json()["code"] == -5022


def test_cancel_flow():
    p = far_limit("BUY")
    oid = place(type="LIMIT", price=p).json()["orderId"]
    assert signed_get("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": oid}).json()["status"] == "NEW"

    r2 = signed_delete("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": oid})
    assert r2.json()["status"] == "CANCELED"

    r3 = signed_delete("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": oid})
    assert r3.json()["code"] == -2011


def test_conditional_type_rejected_with_4120():
    for t in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"):
        body = {"symbol": "BTCUSDT", "side": "SELL", "type": t, "quantity": "0.002",
                "triggerPrice": "1"}
        assert signed_post("/fapi/v1/order", body).json()["code"] == -4120


def test_filters():
    # qty duoi step
    assert place(quantity="0.0001").json()["code"] == -1111
    # tick sai
    assert place(type="LIMIT", price="65000.123", timeInForce="GTC").json()["code"] == -4014
    # notional qua nho
    assert place(symbol="BTCUSDT", quantity="0.001", type="LIMIT",
                 price="100.0", timeInForce="GTC").json()["code"] == -4164


def test_margin_insufficient():
    # 0.5 BTC ~ 32k notional -> margin ~10k > 5000
    r = place(quantity="0.5")
    assert r.json()["code"] == -2019


def test_duplicate_client_order_id():
    p = far_limit("BUY")
    body = {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "0.002",
            "price": p, "timeInForce": "GTC", "newClientOrderId": "trung-id"}
    assert signed_post("/fapi/v1/order", body).status_code == 200
    r2 = signed_post("/fapi/v1/order", body)
    assert r2.json()["code"] == -2010


def test_reduce_only_without_position():
    r = place(side="SELL", reduceOnly="true")
    assert r.json()["code"] == -2021


def test_order_test_endpoint_does_not_create():
    before = len(STORE.orders())
    assert signed_post("/fapi/v1/order/test", {
        "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002",
    }).json() == {}
    assert len(STORE.orders()) == before


def test_fee_recorded():
    place()
    fills = STORE.fills("BTCUSDT")
    assert len(fills) == 1
    fee = Decimal(fills[0]["fee"])
    assert fee > 0


