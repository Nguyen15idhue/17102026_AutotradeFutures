"""Reconcile: lech -> HALT + incident, KHONG tu sua. Khop -> 0."""

import time

import pytest

from app.db.store import connect
from app.exchange.reconcile import Reconciler


class FakeRest:
    def __init__(self, amt="0"):
        self.amt = amt

    def get(self, path, params=None, signed=True):
        if path == "/fapi/v2/positionRisk":
            return [{"symbol": "DOGEUSDT", "positionAmt": self.amt}]
        if path == "/fapi/v1/openOrders":
            return []
        return []


class FakeAlert:
    def __init__(self):
        self.n = 0

    def push(self, key, text):
        return "queued"

    def flush(self):
        self.n += 1
        return 1


@pytest.fixture()
def con():
    c = connect(":memory:")
    yield c
    c.close()


def test_no_diff_no_halt(con):
    r = Reconciler(con, FakeRest("0"), FakeAlert())
    assert r.check() == 0 and r.halted() is False


def test_diff_halts_and_keeps_db(con):
    now = int(time.time() * 1000)
    con.execute(
        "INSERT INTO positions(symbol,amt,entry,updated_ms) VALUES('DOGEUSDT','0','0',?)", (now,)
    )
    r = Reconciler(con, FakeRest("10"), FakeAlert())
    assert r.check() == 1
    assert r.halted() is True
    # khong tu sua: DB van 0
    assert con.execute("SELECT amt FROM positions WHERE symbol='DOGEUSDT'").fetchone()[0] == "0"
    assert con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1


def test_rest_error_no_halt(con):
    class Bad:
        def get(self, path, params=None, signed=True):
            raise RuntimeError("timeout")

    r = Reconciler(con, Bad(), FakeAlert())
    assert r.check() == 0 and r.halted() is False
