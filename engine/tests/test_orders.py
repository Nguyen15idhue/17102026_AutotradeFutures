"""Orders: idempotent clientOrderId, state machine tu user event."""

import pytest

from app.db.store import connect
from app.exchange.orders import OrderManager, new_client_id
from app.exchange.rest import RestError


class FakeRest:
    def __init__(self):
        self.calls = 0

    def post(self, path, params):
        self.calls += 1
        if params.get("newClientOrderId") == "dup-id" or params.get("clientAlgoId") == "dup-id":
            raise RestError(-2010, "dup")
        return {"orderId": 111, "algoId": 222}


@pytest.fixture()
def con():
    c = connect(":memory:")
    yield c
    c.close()


def test_client_id_format():
    cid = new_client_id("mr", "BTCUSDT")
    assert cid.startswith("mr-BTCUSDT-") and len(cid) <= 36


def test_same_id_no_second_send(con):
    fr = FakeRest()
    m = OrderManager(con, fr)
    r1 = m.place("DOGEUSDT", "BUY", "MARKET", "10", client_id="t-id-1")
    r2 = m.place("DOGEUSDT", "BUY", "MARKET", "10", client_id="t-id-1")
    assert fr.calls == 1 and r2.get("deduped") is True
    n = con.execute("SELECT COUNT(*) FROM orders WHERE client_id='t-id-1'").fetchone()[0]
    assert n == 1 and r1["exchange_id"] == "111"


def test_exchange_dup_treated_as_dedup(con):
    m = OrderManager(con, FakeRest())
    r = m.place("DOGEUSDT", "BUY", "MARKET", "10", client_id="dup-id")
    assert r.get("deduped") is True


def test_reject_recorded(con):
    class BadRest:
        def post(self, path, params):
            raise RestError(-2019, "margin")

    m = OrderManager(con, BadRest())
    with pytest.raises(RestError):
        m.place("DOGEUSDT", "BUY", "MARKET", "10", client_id="rej-1")
    st = con.execute("SELECT status FROM orders WHERE client_id='rej-1'").fetchone()[0]
    assert st == "REJECTED"


def test_algo_goes_to_algo_endpoint(con):
    seen = {}

    class R:
        def post(self, path, params):
            seen["path"] = path
            assert params.get("algoType") == "CONDITIONAL"
            return {"algoId": 999}

    m = OrderManager(con, R())
    r = m.place_algo("DOGEUSDT", "SELL", "STOP_MARKET", "0.05", client_id="a-1")
    assert seen["path"] == "/fapi/v1/algoOrder" and r["exchange_id"] == "999"


def test_order_trade_update(con):
    m = OrderManager(con, FakeRest())
    m.place("DOGEUSDT", "BUY", "MARKET", "10", client_id="u-1")
    m.on_order_trade(
        {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "c": "u-1",
                "i": 111,
                "X": "FILLED",
                "s": "DOGEUSDT",
                "S": "BUY",
                "l": "10",
                "L": "0.05",
                "n": "0.0001",
            },
        }
    )
    st = con.execute("SELECT status FROM orders WHERE client_id='u-1'").fetchone()[0]
    assert st == "FILLED"
    f = con.execute("SELECT qty,price FROM fills WHERE order_ref='u-1'").fetchone()
    assert f is not None and float(f[0]) == 10.0 and f[1] == "0.05"
    p = con.execute("SELECT amt FROM positions WHERE symbol='DOGEUSDT'").fetchone()
    assert p and float(p[0]) == 10.0


def test_mock_shape_z_cumulative_no_double_count(con):
    """Mock gui l=0, don fill vao z. Giao lai event 2 lan khong nhan doi."""
    m = OrderManager(con, FakeRest())
    m.place("DOGEUSDT", "BUY", "MARKET", "337", client_id="z-1")
    ev = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "c": "z-1",
            "i": 1,
            "X": "FILLED",
            "s": "DOGEUSDT",
            "S": "BUY",
            "l": "0",
            "z": "337",
            "L": "0",
            "ap": "0.059",
            "n": "0",
        },
    }
    m.on_order_trade(ev)
    m.on_order_trade(ev)  # giao lai
    n = con.execute("SELECT COUNT(*) FROM fills WHERE order_ref='z-1'").fetchone()[0]
    assert n == 1
    p = con.execute("SELECT amt FROM positions WHERE symbol='DOGEUSDT'").fetchone()
    assert p and float(p[0]) == 337.0


def test_algo_update(con):
    con.execute(
        "INSERT INTO orders(client_id,symbol,side,type,qty,status,created_ms,updated_ms)"
        " VALUES('a-9','DOGEUSDT','SELL','STOP_MARKET','0','NEW',1,1)"
    )
    OrderManager(con, FakeRest()).on_algo_update(
        {"e": "ALGO_UPDATE", "a": {"clientAlgoId": "a-9", "algoStatus": "EXPIRED"}}
    )
    st = con.execute("SELECT status FROM orders WHERE client_id='a-9'").fetchone()[0]
    assert st == "EXPIRED"
