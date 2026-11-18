"""Test wiring P1.3: main.build doc config, cli chi chay mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import main as M
from app.config import load as load_cfg
from app.db.store import connect
from app.exec import cli
from app.exec.executor import Executor
from tests.test_executor import FakeRest, mr_req

ROOT = Path(__file__).resolve().parents[2]
CFG = load_cfg(ROOT / "config" / "mvp.mock.yaml")
LIVE = load_cfg(ROOT / "config" / "mvp.live.yaml")


def test_build_returns_cfg_and_executor(tmp_path):
    ctx = M.build(cfg=CFG, rest_client=FakeRest(), db_path=str(tmp_path / "b.db"))
    assert ctx["cfg"].env == "mock"
    assert ctx["ex"] is not None and ctx["mgr"] is not None
    assert ctx["con"].execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    ctx["con"].close()


def test_refresh_market_sets_state(tmp_path):
    con = connect(str(tmp_path / "m.db"))
    ex = Executor(con, FakeRest(), CFG, sleep=lambda _s: None)
    m = ex.refresh_market("BTCUSDT")
    assert m["mid"] == pytest.approx(100.0)
    assert m["spread_bps"] == pytest.approx(20.0)
    assert con.execute("SELECT value FROM runtime_state WHERE key='last_market_ms'").fetchone()
    con.close()


def test_cli_refuses_live(tmp_path):
    con = connect(str(tmp_path / "l.db"))
    with pytest.raises(SystemExit, match="chi dung cho mock"):
        cli.run(["close", "--symbol", "BTCUSDT"], cfg=LIVE, con=con, rest=FakeRest())
    con.close()


def test_cli_open_creates_position(tmp_path):
    con = connect(str(tmp_path / "c.db"))
    rest = FakeRest()
    ex = Executor(con, rest, CFG, sleep=lambda _s: None)
    rc = cli.run(
        ["open", "--symbol", "BTCUSDT", "--side", "BUY", "--stop-bps", "80"],
        cfg=CFG,
        con=con,
        rest=rest,
        ex=ex,
    )
    assert rc == 0
    row = con.execute("SELECT strategy_id, side, state FROM positions").fetchone()
    assert row == ("manual", "LONG", "OPEN")
    con.close()


def test_cli_close_after_open(tmp_path):
    con = connect(str(tmp_path / "c2.db"))
    rest = FakeRest()
    ex = Executor(con, rest, CFG, sleep=lambda _s: None)
    ex.refresh_market("BTCUSDT")
    assert ex.open(mr_req())["ok"]
    rc = cli.run(["close", "--symbol", "BTCUSDT"], cfg=CFG, con=con, rest=rest, ex=ex)
    assert rc == 0
    assert con.execute("SELECT state FROM positions").fetchone()[0] == "CLOSED"
    con.close()


def test_cli_usage_without_args(tmp_path, capsys):
    con = connect(str(tmp_path / "u.db"))
    rc = cli.run([], cfg=CFG, con=con, rest=FakeRest())
    assert rc == 2 and "open" in capsys.readouterr().out
    con.close()
