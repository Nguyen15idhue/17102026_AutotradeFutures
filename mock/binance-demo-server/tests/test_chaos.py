"""M0.9 — chaos: fail rate, 503 unknown, throttle -1008, latency."""
from __future__ import annotations

import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market import MARKET
from tests.test_auth import signed_get, signed_post

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


def chaos(**kw):
    return client.post("/_admin/chaos", json=kw).json()


def test_config_and_reset():
    s = chaos(fail_rate=0.5, latency_ms=10, codes=[-1000])
    assert s["fail_rate"] == 0.5
    assert client.post("/_admin/reset").json()["status"] == "reset"
    assert client.get("/_admin/state").json()["chaos"]["fail_rate"] == 0.0


def test_fail_rate_one_returns_errors():
    chaos(fail_rate=1.0, codes=[-1000])
    r = signed_get("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 1})
    assert r.status_code == 400
    assert r.json()["code"] == -1000


def test_fail_rate_approx():
    chaos(fail_rate=0.3, codes=[-1000])
    ok = 0
    for _ in range(100):
        r = signed_get("/fapi/v1/commissionRate", {"symbol": "BTCUSDT"})
        if r.status_code == 200:
            ok += 1
    # 30% loi -> khoang 70 lan thanh cong
    assert 50 <= ok <= 90, ok


def test_unknown_503_message():
    chaos(fail_rate=1.0, unknown_503=True)
    r = signed_get("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 1})
    assert r.status_code == 503
    assert "Unknown error, please check your request or try again later." in r.json()["msg"]


def test_latency_injected():
    chaos(latency_ms=120)
    t0 = time.time()
    signed_get("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 1})
    assert (time.time() - t0) >= 0.10


def test_ping_not_affected():
    chaos(fail_rate=1.0, unknown_503=True)
    assert client.get("/fapi/v1/ping").status_code == 200


def test_throttle_1008_blocks_normal_order(price):
    price("100000")
    chaos(throttle_1008=True)
    r = signed_post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY",
                                       "type": "MARKET", "quantity": "0.002"})
    assert r.status_code == 503
    assert r.json()["code"] == -1008


def test_throttle_1008_exempts_reduce_only(price):
    price("100000")
    signed_post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY",
                                   "type": "MARKET", "quantity": "0.002"})
    chaos(throttle_1008=True)
    r = signed_post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "SELL",
                                       "type": "MARKET", "quantity": "0.002",
                                       "reduceOnly": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "FILLED"


def test_admin_paths_not_affected():
    chaos(fail_rate=1.0, unknown_503=True)
    assert client.get("/_admin/state").status_code == 200
    assert client.get("/_debug/json").status_code == 200


def test_chaos_off_after_reset():
    chaos(fail_rate=1.0, unknown_503=True)
    client.post("/_admin/reset")
    r = signed_get("/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 1})
    assert r.status_code == 400
    assert r.json()["code"] == -2013
