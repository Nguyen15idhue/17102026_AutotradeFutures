"""Test P1.3 schema: positions mo rong + signals/equity/commands, migration DB cu."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.store import connect

ROOT = Path(__file__).resolve().parents[2]


def test_old_positions_table_migrated(tmp_path):
    """DB tao truoc P1.3 (positions toi gian) phai duoc migrate, khong mat du lieu."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE positions(symbol TEXT PRIMARY KEY, amt TEXT NOT NULL DEFAULT '0',"
        " entry TEXT DEFAULT '0', updated_ms INTEGER NOT NULL)"
    )
    con.execute(
        "INSERT INTO positions(symbol,amt,entry,updated_ms) VALUES('BTCUSDT','0.01','100',1)"
    )
    con.commit()
    con.close()

    db = connect(str(path))
    cols = {r[1] for r in db.execute("PRAGMA table_info(positions)")}
    assert {"strategy_id", "side", "sl", "tp", "risk_usd", "opened_ms", "state"} <= cols
    row = db.execute(
        "SELECT amt, strategy_id, state, risk_usd FROM positions WHERE symbol='BTCUSDT'"
    ).fetchone()
    assert row == ("0.01", "", "OPEN", 0)
    db.close()

    db2 = connect(str(path))  # idempotent
    assert db2.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1
    db2.close()


def test_new_tables_roundtrip(tmp_path):
    db = connect(str(tmp_path / "p13.db"))
    db.execute(
        "INSERT INTO signals(strategy_id,symbol,side,ts_ms,entry,stop,tp,risk_usd,reason,status)"
        " VALUES('mean_reversion','BTCUSDT','BUY',1,'100','95','105',0.5,'z=-2','NEW')"
    )
    db.execute("INSERT INTO equity(ts_ms,equity,balance,unrealized) VALUES(1,300,300,0)")
    db.execute("INSERT INTO commands(action,payload,status,created_ms) VALUES('pause','','NEW',1)")
    assert db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    assert db.execute("SELECT equity FROM equity WHERE ts_ms=1").fetchone()[0] == 300
    assert db.execute("SELECT action FROM commands").fetchone()[0] == "pause"
    db.close()


def test_migrate_real_p12_db_if_present(tmp_path):
    """Ban sao data/p1.2.db phai migrate duoc (bo qua neu may khong co file)."""
    src = ROOT / "data" / "p1.2.db"
    if not src.is_file():
        return
    dst = tmp_path / "copy.db"
    dst.write_bytes(src.read_bytes())
    db = connect(str(dst))
    cols = {r[1] for r in db.execute("PRAGMA table_info(positions)")}
    assert "strategy_id" in cols and "risk_usd" in cols
    db.close()
