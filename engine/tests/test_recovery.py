"""Test P1.3 trailing/close/recovery: make-before-break, SL luon ton tai."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import load as load_cfg
from app.db.store import connect
from app.exec import recovery
from app.exec.executor import Executor
from tests.test_executor import FakeRest, mr_req
from tests.test_risk_limits import inp

ROOT = Path(__file__).resolve().parents[2]
CFG = load_cfg(ROOT / "config" / "mvp.mock.yaml")


class RecoverRest(FakeRest):
    """Fake REST cho recovery: positionRisk + openAlgoOrders theo tham so."""

    def __init__(self, positions=None, algos=None):
        super().__init__()
        self.positions = positions or []
        self.algos = algos or []

    def get(self, path, params=None, signed=True, max_tries=4):
        if path == "/fapi/v2/positionRisk":
            self.calls.append(("GET", path, {}, 0.0))
            return self.positions
        if path == "/fapi/v1/openAlgoOrders":
            self.calls.append(("GET", path, {}, 0.0))
            return self.algos
        return super().get(path, params, signed, max_tries)


def _setup(tmp_path, rest=None):
    con = connect(str(tmp_path / "p13.db"))
    rest = rest or FakeRest()
    ex = Executor(con, rest, CFG, sleep=lambda _s: None)
    return con, rest, ex


def _open_position(con, rest, ex, symbol="BTCUSDT"):
    r = ex.open(mr_req(symbol=symbol), inputs=inp())
    assert r["ok"], r
    return r


def test_trail_places_before_cancel(tmp_path):
    con, rest, ex = _setup(tmp_path)
    first = _open_position(con, rest, ex)
    before = len(rest.calls)
    out = ex.trail("BTCUSDT", 99.5)
    calls = rest.calls[before:]
    posts = [i for i, c in enumerate(calls) if c[0] == "POST" and c[1] == "/fapi/v1/algoOrder"]
    deletes = [i for i, c in enumerate(calls) if c[0] == "DELETE" and c[1] == "/fapi/v1/algoOrder"]
    assert posts and deletes and posts[0] < deletes[0]
    assert out["old_id"] == first["sl_id"] and out["sl_id"] != first["sl_id"]
    row = con.execute("SELECT sl, sl_id FROM positions WHERE symbol='BTCUSDT'").fetchone()
    assert row[1] == out["sl_id"] and row[0] == "99.5"
    con.close()


def test_trail_cancel_failure_halts(tmp_path):
    con, rest, ex = _setup(tmp_path)
    _open_position(con, rest, ex)

    def boom(*_a, **_kw):
        raise RuntimeError("cancel fail")

    ex._mgr.cancel_algo = boom
    with pytest.raises(RuntimeError):
        ex.trail("BTCUSDT", 99.5)
    assert con.execute("SELECT value FROM runtime_state WHERE key='halted'").fetchone()[0] == "1"
    assert con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
    con.close()


def test_close_market_reduce_only_and_closed(tmp_path):
    con, rest, ex = _setup(tmp_path)
    _open_position(con, rest, ex)
    out = ex.close("BTCUSDT", "test")
    assert out["ok"]
    order = rest.posts("/fapi/v1/order")[-1][2]
    assert order["type"] == "MARKET" and order["reduceOnly"] == "true"
    row = con.execute("SELECT amt, state FROM positions WHERE symbol='BTCUSDT'").fetchone()
    assert row == ("0", "CLOSED")
    con.close()


def test_close_when_flat_is_noop(tmp_path):
    con, rest, ex = _setup(tmp_path)
    assert ex.close("BTCUSDT")["reason"] == "already_flat"
    assert rest.posts("/fapi/v1/order") == []
    con.close()


def test_recovery_replaces_missing_sl(tmp_path):
    con, rest, ex = _setup(tmp_path)
    _open_position(con, rest, ex)
    con.execute("UPDATE positions SET sl_id='' WHERE symbol='BTCUSDT'")
    rrest = RecoverRest(positions=[{"symbol": "BTCUSDT", "positionAmt": "0.750"}], algos=[])
    rep = recovery.recover(con, rrest, CFG, ex=ex)
    assert rep["repaired_sl"] == 1 and rep["halted"] == 0
    row = con.execute("SELECT sl_id FROM positions WHERE symbol='BTCUSDT'").fetchone()
    assert row[0]
    con.close()


def test_recovery_keeps_existing_sl(tmp_path):
    con, rest, ex = _setup(tmp_path)
    _open_position(con, rest, ex)
    rrest = RecoverRest(
        positions=[{"symbol": "BTCUSDT", "positionAmt": "0.750"}],
        algos=[{"symbol": "BTCUSDT", "type": "STOP_MARKET", "algoStatus": "NEW"}],
    )
    before = len(rrest.calls)
    rep = recovery.recover(con, rrest, CFG, ex=ex)
    assert rep["repaired_sl"] == 0
    assert [c for c in rrest.calls[before:] if c[0] == "POST"] == []
    con.close()


def test_recovery_db_position_missing_on_exchange_halts(tmp_path):
    con, rest, ex = _setup(tmp_path)
    _open_position(con, rest, ex)
    rrest = RecoverRest(positions=[], algos=[])
    rep = recovery.recover(con, rrest, CFG, ex=ex)
    assert rep["halted"] >= 1
    assert con.execute("SELECT value FROM runtime_state WHERE key='halted'").fetchone()[0] == "1"
    con.close()


def test_recovery_exchange_position_not_in_db_halts(tmp_path):
    con, rest, ex = _setup(tmp_path)
    rrest = RecoverRest(positions=[{"symbol": "ETHUSDT", "positionAmt": "-1.0"}], algos=[])
    rep = recovery.recover(con, rrest, CFG, ex=ex)
    assert rep["halted"] >= 1
    con.close()
