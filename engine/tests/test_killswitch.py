"""Test kill switch P1.3: 4 action, action la bi tu choi, pause chan entry, < 2s."""

from __future__ import annotations

import time
from pathlib import Path

from app.config import load as load_cfg
from app.db.store import connect
from app.exec.executor import Executor
from app.ops import commands as C
from tests.test_executor import FakeRest, mr_req
from tests.test_risk_limits import inp

ROOT = Path(__file__).resolve().parents[2]
CFG = load_cfg(ROOT / "config" / "mvp.mock.yaml")


def _setup(tmp_path):
    con = connect(str(tmp_path / "p13.db"))
    rest = FakeRest()
    ex = Executor(con, rest, CFG, sleep=lambda _s: None)
    return con, rest, ex


def _state(con, key):
    row = con.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def test_pause_and_resume(tmp_path):
    con, _rest, ex = _setup(tmp_path)
    C.enqueue(con, "pause")
    assert C.handle_once(con, ex)["done"] == 1
    assert _state(con, "paused") == "1"
    # pause phai chan entry
    r = ex.open(mr_req(), inputs=inp(paused=True))
    assert not r["ok"] and r["reason"] == "paused"
    C.enqueue(con, "resume")
    C.handle_once(con, ex)
    assert _state(con, "paused") == "0"
    con.close()


def test_unknown_action_rejected_with_incident(tmp_path):
    con, _rest, ex = _setup(tmp_path)
    C.enqueue(con, "open_long")
    out = C.handle_once(con, ex)
    assert out["rejected"] == 1
    assert con.execute("SELECT status FROM commands").fetchone()[0] == "REJECTED"
    assert con.execute("SELECT kind FROM incidents").fetchone()[0] == "bad_command"
    con.close()


def test_flatten_closes_all_positions(tmp_path):
    con, rest, ex = _setup(tmp_path)
    assert ex.open(mr_req(symbol="BTCUSDT"), inputs=inp())["ok"]
    C.enqueue(con, "flatten")
    out = C.handle_once(con, ex)
    assert out["done"] == 1
    rows = con.execute("SELECT state, amt FROM positions").fetchall()
    assert rows == [("CLOSED", "0")]
    assert con.execute("SELECT status, done_ms FROM commands").fetchone()[0] == "DONE"
    con.close()


def test_stop_flattens_and_halts(tmp_path):
    con, _rest, ex = _setup(tmp_path)
    assert ex.open(mr_req(symbol="BTCUSDT"), inputs=inp())["ok"]
    C.enqueue(con, "stop")
    C.handle_once(con, ex)
    assert _state(con, "halted") == "1"
    assert con.execute("SELECT state FROM positions").fetchone()[0] == "CLOSED"
    con.close()


def test_handle_once_is_idempotent(tmp_path):
    con, _rest, ex = _setup(tmp_path)
    C.enqueue(con, "pause")
    C.handle_once(con, ex)
    assert C.handle_once(con, ex)["done"] == 0
    assert con.execute("SELECT COUNT(*) FROM commands WHERE status='DONE'").fetchone()[0] == 1
    con.close()


def test_kill_switch_under_2s(tmp_path):
    con, _rest, ex = _setup(tmp_path)
    for i in range(3):
        assert ex.open(mr_req(symbol=f"S{i}USDT"), inputs=inp())["ok"]
    C.enqueue(con, "stop")
    t0 = time.monotonic()
    C.handle_once(con, ex)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0
    assert _state(con, "halted") == "1"
    con.close()
