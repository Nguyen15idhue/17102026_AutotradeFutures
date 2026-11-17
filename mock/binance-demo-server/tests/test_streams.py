"""M0.8 â€” user data stream: listenKey lifecycle + WS event."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import CFG
from app.main import app
from app.market import MARKET
from app.store import STORE
from app.streams import HUB
from tests.test_auth import signed_delete, signed_post, signed_put

client = TestClient(app)


@pytest.fixture
def price(monkeypatch):
    def apply(value: str):
        p = Decimal(value)
        monkeypatch.setattr(MARKET, "last_price", lambda s: p)
        monkeypatch.setattr(MARKET, "premium_index", lambda s: {
            "symbol": s, "markPrice": str(p), "indexPrice": str(p),
            "estimatedSettlePrice": str(p), "lastFundingRate": "0.0001",
            "nextFundingTime": 0, "interestRate": "0.0001", "time": 0})
        return p
    return apply


def new_key() -> str:
    r = signed_post("/fapi/v1/listenKey", {})
    assert r.status_code == 200
    return r.json()["listenKey"]


def test_listenkey_lifecycle():
    k1 = new_key()
    assert len(k1) > 20
    # tao lan 2 -> tra lai key dang hoat dong
    assert signed_post("/fapi/v1/listenKey", {}).json()["listenKey"] == k1
    # keepalive
    assert signed_put("/fapi/v1/listenKey", {"listenKey": k1}).status_code == 200
    # key la -> -1125
    assert signed_put("/fapi/v1/listenKey", {"listenKey": "khong-ton-tai"}).json()["code"] == -1125
    # close
    assert signed_delete("/fapi/v1/listenKey", {"listenKey": k1}).status_code == 200


def test_ws_receives_order_update(price):
    price("100000")
    key = new_key()
    with client.websocket_connect(f"/ws/{key}") as ws:
        signed_post("/fapi/v1/order", {
            "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"})
        got = ws.receive_json()
    assert got["e"] == "ORDER_TRADE_UPDATE"
    assert got["o"]["s"] == "BTCUSDT"
    assert got["o"]["X"] in ("NEW", "FILLED")


def test_ws_receives_algo_update(price):
    price("100000")
    key = new_key()
    signed_post("/fapi/v1/order", {
        "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"})
    with client.websocket_connect(f"/ws/{key}") as ws:
        signed_post("/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
            "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true"})
        frame = ws.receive_json()
    assert frame["e"] == "ALGO_UPDATE"
    assert frame["o"]["X"] == "NEW"
    assert frame["o"]["o"] == "STOP_MARKET"


def test_ws_private_path(price):
    price("100000")
    key = new_key()
    with client.websocket_connect(f"/private/ws/{key}") as ws:
        signed_post("/fapi/v1/order", {
            "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"})
        got = ws.receive_json()
    assert got["e"] == "ORDER_TRADE_UPDATE"


def test_ws_invalid_key_closes():
    with client.websocket_connect("/ws/key-sai") as ws:
        msg = ws.receive_json()
        assert msg["code"] == -1125


def test_listenkey_expired_broadcast(monkeypatch):
    monkeypatch.setattr(CFG, "listenkey_ttl_s", 1)
    key = new_key()
    HUB._keys[key] = 0.0  # ep het han ngay
    HUB.check_expired()
    kinds = [e["kind"] for e in STORE.events(5)]
    assert "listenKeyExpired" in kinds
    assert not HUB.is_valid(key)


def test_ws_ordering_is_sequential(price):
    price("100000")
    key = new_key()
    with client.websocket_connect(f"/ws/{key}") as ws:
        signed_post("/fapi/v1/order", {
            "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.002"})
        f1 = ws.receive_json()
        f2 = ws.receive_json()
    # 2 event dau cua 1 lenh: ORDER_TRADE_UPDATE (NEW) roi ... (FILLED) hoac ACCOUNT_UPDATE
    assert f1["e"] == "ORDER_TRADE_UPDATE"
    assert f2["E"] >= f1["E"]

