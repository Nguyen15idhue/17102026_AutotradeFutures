"""M0.5 â€” account state: wallet, vi the, uPnL, margin, thanh ly, persist."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app import account as A
from app.main import app
from app.store import STORE
from tests.test_auth import signed_get, signed_post

client = TestClient(app)


def test_initial_balance():
    r = signed_get("/fapi/v2/balance")
    assert r.status_code == 200
    assert r.json()[0]["balance"] == "5000.00000000"
    assert r.json()[0]["availableBalance"] == "5000.00000000"


def test_account_shape():
    body = signed_get("/fapi/v2/account").json()
    for k in ("canTrade", "totalWalletBalance", "availableBalance", "assets", "positions"):
        assert k in body
    assert body["assets"][0]["asset"] == "USDT"
    assert body["positions"] == []


def test_fill_long_updates_position_and_fee():
    qty = Decimal("0.01")
    price = Decimal("65000")
    res = A.apply_fill("BTCUSDT", "BUY", qty, price, maker=True)
    assert res["position_amt"] == qty
    fee = price * qty * Decimal("0.0002")
    assert res["fee"] == fee
    assert A.wallet() == Decimal("5000") - fee

    r = signed_get("/fapi/v2/positionRisk").json()
    assert len(r) == 1
    assert r[0]["positionAmt"] == "0.01"
    assert Decimal(r[0]["entryPrice"]) == price


def test_unrealized_sign_long_short():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("60000"), maker=False)
    mark = A.mark_price("BTCUSDT")
    upnl = A.unrealized("BTCUSDT")
    assert (upnl > 0) == (mark > Decimal("60000"))

    STORE.init(":memory:", Decimal("5000"))
    A.apply_fill("ETHUSDT", "SELL", Decimal("0.1"), Decimal("1800"), maker=False)
    mark2 = A.mark_price("ETHUSDT")
    upnl2 = A.unrealized("ETHUSDT")
    assert (upnl2 > 0) == (mark2 < Decimal("1800"))


def test_available_reduced_by_margin():
    before = A.available()
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=True)
    after = A.available()
    assert after < before
    # margin = notional/leverage = 650/3
    spent = before - after
    assert Decimal("200") < spent < Decimal("240")


def test_realized_pnl_on_close():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("60000"), maker=True)
    res = A.apply_fill("BTCUSDT", "SELL", Decimal("0.01"), Decimal("61000"), maker=True)
    assert res["realized"] == Decimal("10.0")
    assert res["position_amt"] == 0
    assert Decimal(STORE.position("BTCUSDT")["position_amt"]) == 0
    assert abs(A.wallet() - Decimal("5009.758")) < Decimal("0.001")


def test_flip_position():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("60000"), maker=False)
    res = A.apply_fill("BTCUSDT", "SELL", Decimal("0.03"), Decimal("61000"), maker=False)
    assert res["position_amt"] == Decimal("-0.02")
    assert res["entry_price"] == Decimal("61000")


def test_liquidation_price_formula():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=False)
    p = STORE.position("BTCUSDT")
    liq = A.liquidation_price(p)
    # long 3x, mmr 0.4%: entry*(1-1/3)/(1-0.004)
    expect = Decimal("65000") * (Decimal(1) - Decimal(1) / Decimal(3)) / Decimal("0.996")
    assert abs(liq - expect) < Decimal("1")


def test_set_leverage_and_margin_type():
    r = signed_post("/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": "5"})
    assert r.json()["leverage"] == 5
    r2 = signed_post("/fapi/v1/marginType", {"symbol": "BTCUSDT", "marginType": "ISOLATED"})
    assert r2.json()["code"] == 200


def test_margin_type_blocked_with_position():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=False)
    r = signed_post("/fapi/v1/marginType", {"symbol": "BTCUSDT", "marginType": "CROSSED"})
    assert r.json()["code"] == -4048


def test_income_records():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=False)
    rows = signed_get("/fapi/v1/income").json()
    types = {r["incomeType"] for r in rows}
    assert "COMMISSION" in types


def test_persist_across_reinit(tmp_path):
    path = str(tmp_path / "mock.db")
    STORE.init(path, Decimal("5000"))
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=True)
    w = A.wallet()
    amt = A.position_amt("BTCUSDT")
    STORE.close()
    STORE.init(path, Decimal("5000"))
    assert A.wallet() == w
    assert A.position_amt("BTCUSDT") == amt


def test_debug_endpoint_reflects_state():
    A.apply_fill("BTCUSDT", "BUY", Decimal("0.01"), Decimal("65000"), maker=True)
    d = client.get("/_debug/json").json()
    assert d["account"]["wallet"] != "0"
    assert len(d["positions"]) == 1
    assert d["positions"][0]["symbol"] == "BTCUSDT"

