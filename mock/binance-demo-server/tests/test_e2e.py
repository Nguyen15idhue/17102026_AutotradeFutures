"""M0.11 — E2E: kich ban nhieu buoc + bat bien so sach.

Khong nen thoi gian; dung gia co dinh theo buoc de tat dinh.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app import account as A
from app.algo import ALGO
from app.market import MARKET
from app.orders import ENGINE
from app.store import STORE
from tests.test_auth import signed_post


@pytest.fixture
def price(monkeypatch):
    holder = {"p": Decimal("100000")}

    def set_price(value: str):
        holder["p"] = Decimal(value)

    monkeypatch.setattr(MARKET, "last_price", lambda s: holder["p"])
    monkeypatch.setattr(MARKET, "premium_index", lambda s: {
        "symbol": s, "markPrice": str(holder["p"]), "indexPrice": str(holder["p"]),
        "estimatedSettlePrice": str(holder["p"]), "lastFundingRate": "0.0001",
        "nextFundingTime": 0, "interestRate": "0.0001", "time": 0})
    return set_price


def market(side: str, qty: str = "0.002"):
    return signed_post("/fapi/v1/order", {
        "symbol": "BTCUSDT", "side": side, "type": "MARKET", "quantity": qty})


def wallet_formula() -> Decimal:
    """wallet = initial + realized - fees (lay tu bang income)."""
    initial = Decimal(STORE.account()["initial_balance"])
    pnl = sum((Decimal(r["income"]) for r in STORE.incomes(1000) if r["income_type"] == "REALIZED_PNL"),
              Decimal("0"))
    fee = sum((Decimal(r["income"]) for r in STORE.incomes(1000) if r["income_type"] == "COMMISSION"),
              Decimal("0"))
    return initial + pnl + fee


def position_from_fills() -> Decimal:
    total = Decimal("0")
    for f in STORE.fills("BTCUSDT", 1000):
        q = Decimal(f["qty"])
        total += q if f["side"] == "BUY" else -q
    return total


def assert_invariants():
    q = Decimal("0.00000001")
    assert A.position_amt("BTCUSDT").quantize(q) == position_from_fills().quantize(q), "position != tong fills"
    assert A.wallet().quantize(q) == wallet_formula().quantize(q), "wallet != initial + pnl - fee"
    for p in STORE.positions():
        if Decimal(p["position_amt"]) == 0:
            continue
        liq = A.liquidation_price(p)
        mark = A.mark_price(p["symbol"])
        if Decimal(p["position_amt"]) > 0:
            assert liq < mark, "gia thanh ly long phai duoi mark"
        else:
            assert liq > mark, "gia thanh ly short phai tren mark"


def test_full_trade_cycle(price):
    price("100000")
    market("BUY")
    assert_invariants()

    aid = signed_post("/fapi/v1/algoOrder", {
        "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": "SELL",
        "type": "STOP_MARKET", "triggerPrice": "95000", "closePosition": "true"}).json()["algoId"]

    price("94000")
    ALGO.tick()
    assert STORE.algo(algo_id=aid)["status"] == "FINISHED"
    assert A.position_amt("BTCUSDT") == 0
    assert_invariants()


def test_random_ops_keep_invariants(price):
    rng = random.Random(7)
    price("100000")
    for _i in range(30):
        price(str(90000 + rng.randint(0, 20000)))
        side = "BUY" if rng.random() < 0.5 else "SELL"
        market(side)
        assert_invariants()


def test_sl_always_exists_after_entry(price):
    price("100000")
    for i in range(5):
        market("BUY" if i % 2 == 0 else "SELL", "0.002")
        mark = A.mark_price("BTCUSDT")
        amt = A.position_amt("BTCUSDT")
        assert amt != 0
        trig = (mark * Decimal("0.95")).quantize(Decimal("0.1")) if amt > 0 \
            else (mark * Decimal("1.05")).quantize(Decimal("0.1"))
        side = "SELL" if amt > 0 else "BUY"
        r = signed_post("/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": "BTCUSDT", "side": side,
            "type": "STOP_MARKET", "triggerPrice": str(trig), "closePosition": "true"})
        assert r.status_code == 200, r.text
        assert STORE.algos(symbol="BTCUSDT", status="NEW")
        signed_post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": side,
                                       "type": "MARKET", "quantity": str(abs(amt))})
        ALGO.tick()
        assert_invariants()


def test_no_negative_balance_after_fees(price):
    price("100000")
    market("BUY")
    market("SELL")
    assert A.wallet() > 0
    assert A.available() >= 0


def test_engine_tick_idempotent(price):
    price("100000")
    ENGINE.place({"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
                  "quantity": "0.002", "price": "50000", "timeInForce": "GTC",
                  "timestamp": "0"})
    h = STORE.state_hash()
    ENGINE.tick()
    ENGINE.tick()
    assert STORE.state_hash() == h  # khong khop -> khong doi state


