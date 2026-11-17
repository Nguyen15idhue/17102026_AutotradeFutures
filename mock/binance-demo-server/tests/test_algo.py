"""M0.7 — algo engine: vong doi SL/TP, closePosition, EXPIRED, priceProtect.

Test dung gia co dinh (monkeypatch) de tat dinh hoan toan.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app import account as A
from app.algo import ALGO
from app.market import MARKET
from app.store import STORE
from tests.test_auth import signed_delete, signed_get, signed_post


@pytest.fixture
def price(monkeypatch):
    """Dat gia co dinh cho moi symbol."""
    def apply(value: str) -> Decimal:
        p = Decimal(value)
        monkeypatch.setattr(MARKET, "last_price", lambda s: p)
        monkeypatch.setattr(MARKET, "premium_index", lambda s: {
            "symbol": s, "markPrice": str(p), "indexPrice": str(p),
            "estimatedSettlePrice": str(p), "lastFundingRate": "0.00010000",
            "nextFundingTime": 0, "interestRate": "0.00010000", "time": 0,
        })
        return p
    return apply


def open_long(**kw):
    body = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"}
    body.update({k: str(v) for k, v in kw.items()})
    return signed_post("/fapi/v1/order", body)


def place_algo(**kw):
    body = {"algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
            "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true",
            "workingType": "MARK_PRICE", "priceProtect": "false"}
    body.update({k: str(v) for k, v in kw.items()})
    return signed_post("/fapi/v1/algoOrder", body)


def test_algo_created_with_status_new(price):
    price("100000")
    open_long()
    r = place_algo()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["algoStatus"] == "NEW"
    assert body["closePosition"] is True
    assert body["orderType"] == "STOP_MARKET"
    assert signed_get("/fapi/v1/openAlgoOrders").json()["total"] == 1


def test_sl_triggers_and_closes_position(price):
    price("100000")
    open_long()
    assert A.position_amt("BTCUSDT") == Decimal("0.002")
    aid = place_algo(triggerPrice="95000").json()["algoId"]

    price("94000")
    ALGO.tick()

    assert STORE.algo(algo_id=aid)["status"] == "FINISHED"
    assert A.position_amt("BTCUSDT") == 0


def test_sl_does_not_trigger_when_price_above(price):
    price("100000")
    open_long()
    aid = place_algo(triggerPrice="95000").json()["algoId"]
    price("98000")
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "NEW"
    assert A.position_amt("BTCUSDT") == Decimal("0.002")


def test_take_profit_direction(price):
    price("100000")
    open_long()
    aid = place_algo(type="TAKE_PROFIT_MARKET", triggerPrice="105000").json()["algoId"]
    price("106000")
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "FINISHED"
    assert A.position_amt("BTCUSDT") == 0


def test_stop_buy_for_short(price):
    price("100000")
    open_long(side="SELL")
    assert A.position_amt("BTCUSDT") < 0
    aid = place_algo(side="BUY", triggerPrice="105000").json()["algoId"]
    price("106000")
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "FINISHED"
    assert A.position_amt("BTCUSDT") == 0


def test_expired_when_position_closed_manually(price):
    price("100000")
    open_long()
    aid = place_algo(triggerPrice="95000").json()["algoId"]

    open_long(side="SELL")  # dong tay
    assert A.position_amt("BTCUSDT") == 0
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "EXPIRED"


def test_close_position_cannot_have_quantity(price):
    price("100000")
    open_long()
    assert place_algo(quantity="0.002").json()["code"] == -1106
    assert place_algo(closePosition="true", reduceOnly="true").json()["code"] == -1106


def test_would_immediately_trigger(price):
    price("100000")
    open_long()
    # SL SELL dat CAO hon gia -> kich hoat ngay
    assert place_algo(triggerPrice="110000").json()["code"] == -2020


def test_trigger_tick_validation(price):
    price("100000")
    open_long()
    assert place_algo(triggerPrice="12345.678").json()["code"] == -4014


def test_price_protect_blocks_trigger(price, monkeypatch):
    price("100000")
    open_long()
    aid = place_algo(triggerPrice="95000", priceProtect="true").json()["algoId"]

    # mark 94000 nhung last 100000 -> lech 6% > triggerProtect 5% -> khong trigger
    monkeypatch.setattr(MARKET, "premium_index", lambda s: {
        "symbol": s, "markPrice": "94000", "indexPrice": "100000",
        "estimatedSettlePrice": "100000", "lastFundingRate": "0.0001",
        "nextFundingTime": 0, "interestRate": "0.0001", "time": 0,
    })
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "NEW"


def test_cancel_algo_and_duplicate_id(price):
    price("100000")
    open_long()
    body = {"algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
            "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true",
            "clientAlgoId": "sl-1"}
    aid = signed_post("/fapi/v1/algoOrder", body).json()["algoId"]
    assert signed_post("/fapi/v1/algoOrder", body).json()["code"] == -2010

    r = signed_delete("/fapi/v1/algoOrder", {"algoId": aid})
    assert r.json()["algoStatus"] == "CANCELED"
    assert signed_get("/fapi/v1/openAlgoOrders").json()["total"] == 0


def test_cancel_all_algo(price):
    price("100000")
    open_long()
    place_algo(triggerPrice="95000")
    place_algo(triggerPrice="94000")
    assert signed_get("/fapi/v1/openAlgoOrders").json()["total"] == 2
    r = signed_delete("/fapi/v1/algoOpenOrders", {"symbol": "BTCUSDT"})
    assert r.json()["count"] == 2


def test_algo_update_event_published(price):
    price("100000")
    open_long()
    place_algo()
    assert any(e["kind"] == "ALGO_UPDATE" for e in STORE.events(10))


def test_history_orders(price):
    price("100000")
    open_long()
    place_algo(triggerPrice="95000")
    h = signed_get("/fapi/v1/historicalAlgoOrders").json()
    assert h["total"] == 1
    assert h["orders"][0]["algoStatus"] == "NEW"
