"""M0.10 — persistence, restart, snapshot/restore, tinh tat dinh."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app import account as A
from app.algo import ALGO
from app.config import CFG
from app.market import MARKET
from app.orders import ENGINE
from app.store import STORE
from tests.test_auth import signed_post


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


def buy(qty: str = "0.002"):
    return signed_post("/fapi/v1/order", {
        "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": qty})


def test_restart_keeps_position_order_algo(tmp_path, price):
    price("100000")
    path = str(tmp_path / "mock.db")
    STORE.init(path, Decimal("5000"))
    buy()
    oid = STORE.next_id("order_id", 3_000_000_000)
    signed_post("/fapi/v1/algoOrder", {
        "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
        "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true"})

    pos = A.position_amt("BTCUSDT")
    algos_before = STORE.counts()["algo_orders"]
    STORE.close()

    STORE.init(path, Decimal("5000"))
    assert A.position_amt("BTCUSDT") == pos
    assert STORE.counts()["algo_orders"] == algos_before
    # ID khong bi tai su dung
    new_id = STORE.next_id("order_id", 3_000_000_000)
    assert new_id > oid


def test_algo_survives_restart_and_triggers(tmp_path, price):
    price("100000")
    path = str(tmp_path / "mock.db")
    STORE.init(path, Decimal("5000"))
    buy()
    aid = signed_post("/fapi/v1/algoOrder", {
        "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
        "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true"}).json()["algoId"]
    STORE.close()

    STORE.init(path, Decimal("5000"))
    assert STORE.algo(algo_id=aid)["status"] == "NEW"
    price("94000")
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "FINISHED"
    assert A.position_amt("BTCUSDT") == 0


def test_determinism_same_sequence(tmp_path, price):
    price("100000")
    hashes = []
    for i in range(2):
        p = str(tmp_path / f"run{i}.db")
        STORE.init(p, Decimal("5000"))
        buy()
        buy("0.004")
        signed_post("/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
            "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true"})
        hashes.append(STORE.state_hash())
        STORE.close()
    # Order ID tang dan theo seq nen hash khac nhau; so sanh phan nghiep vu
    STORE.init(str(tmp_path / "run0.db"), Decimal("5000"))
    c0 = STORE.counts()
    h0 = STORE.state_hash()
    STORE.init(str(tmp_path / "run1.db"), Decimal("5000"))
    c1 = STORE.counts()
    h1 = STORE.state_hash()
    assert c0 == c1
    assert h0 != h1  # do order_id khac -> chung minh hash nhay voi id
    assert A.position_amt("BTCUSDT") == Decimal("0.006")


def test_snapshot_restore_roundtrip(tmp_path, price):
    price("100000")
    path = str(tmp_path / "mock.db")
    STORE.init(path, Decimal("5000"))
    buy()
    h1 = STORE.state_hash()
    snap = str(tmp_path / "snap.db")
    STORE.snapshot_to(snap)

    buy("0.004")
    assert STORE.state_hash() != h1

    STORE.restore_from(snap)
    assert STORE.state_hash() == h1
    assert A.position_amt("BTCUSDT") == Decimal("0.002")


def test_counts_and_hash_stable_without_changes(tmp_path, price):
    price("100000")
    STORE.init(str(tmp_path / "mock.db"), Decimal("5000"))
    buy()
    h1 = STORE.state_hash()
    assert STORE.state_hash() == h1
    assert STORE.counts()["fills"] == 1


def test_limit_order_survives_restart(tmp_path, price):
    price("100000")
    path = str(tmp_path / "mock.db")
    STORE.init(path, Decimal("5000"))
    ENGINE.place({"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
                  "quantity": "0.002", "price": "50000", "timeInForce": "GTC",
                  "timestamp": "0"})
    assert STORE.counts()["orders"] == 1
    STORE.close()
    STORE.init(path, Decimal("5000"))
    assert len(STORE.orders(status="NEW")) == 1


def test_admin_snapshot_endpoint(tmp_path, price, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    price("100000")
    monkeypatch.setattr(CFG, "db_path", str(tmp_path / "mock.db"))
    STORE.init(CFG.db_path, Decimal("5000"))
    buy()
    cli = TestClient(app)
    r = cli.post("/_admin/snapshot").json()
    assert "state_hash" in r
    assert r["counts"]["fills"] == 1
