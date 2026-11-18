"""Test P1.2 persist: upsert idempotent bars/features/regime, doc lai dung."""

from __future__ import annotations

from app.data import persist
from app.db.store import connect
from app.regime.types import RegimeLabel, RegimeResult

TF = "15m"


def _con(tmp_path):
    return connect(str(tmp_path / "p12.db"))


def _feature(ts: int, **over) -> dict:
    f = {
        "ts": ts,
        "atr": 10.0,
        "adx": 15.0,
        "bb_mid": 100.0,
        "bb_up": 110.0,
        "bb_dn": 90.0,
        "bbw": 0.2,
        "bbw_pct": 30.0,
        "z": 0.5,
        "vol_pct": 40.0,
        "range_24h": 20.0,
        "range_pos": 0.5,
        "ema50": 101.0,
        "ema200": 100.0,
        "oi": None,
        "funding": None,
        "allow_mr": True,
    }
    f.update(over)
    return f


def test_bars_upsert_idempotent(tmp_path):
    con = _con(tmp_path)
    bars = [{"open_time": 1_000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "closed": True}]
    assert persist.upsert_bars(con, "BTCUSDT", TF, bars) == 1
    persist.upsert_bars(con, "BTCUSDT", TF, bars)
    n = con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    assert n == 1
    persist.upsert_bars(con, "BTCUSDT", TF, [dict(bars[0], c=9.0)])
    assert con.execute("SELECT c FROM bars").fetchone()[0] == 9.0


def test_features_upsert_idempotent_and_nullable(tmp_path):
    con = _con(tmp_path)
    feats = [_feature(1_000), _feature(2_000, oi=123.0, funding=-0.0002)]
    assert persist.upsert_features(con, "BTCUSDT", TF, feats) == 2
    persist.upsert_features(con, "BTCUSDT", TF, feats)
    assert con.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 2
    rows = persist.read_features(con, "BTCUSDT", TF, 0, 9_999)
    assert [r["ts"] for r in rows] == [1_000, 2_000]
    assert rows[0]["oi"] is None and rows[1]["oi"] == 123.0
    assert rows[0]["allow_mr"] == 1


def test_features_skip_none_rows(tmp_path):
    con = _con(tmp_path)
    assert persist.upsert_features(con, "BTCUSDT", TF, [None, _feature(1_000)]) == 1
    assert con.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 1


def test_regime_upsert_and_read_range(tmp_path):
    con = _con(tmp_path)
    rows = [
        (1_000, RegimeResult(RegimeLabel.RANGE, RegimeLabel.RANGE, 1.0, "range:ok")),
        (2_000, RegimeResult(RegimeLabel.CRISIS, RegimeLabel.CRISIS, 1.0, "crisis:x")),
    ]
    assert persist.upsert_regime(con, "BTCUSDT", rows) == 2
    persist.upsert_regime(con, "BTCUSDT", rows)
    assert con.execute("SELECT COUNT(*) FROM regime").fetchone()[0] == 2
    got = persist.read_regime(con, "BTCUSDT", 1_500, 2_500)
    assert len(got) == 1 and got[0]["label"] == "CRISIS" and got[0]["ts"] == 2_000


def test_features_and_regime_join_by_ts(tmp_path):
    con = _con(tmp_path)
    persist.upsert_features(con, "BTCUSDT", TF, [_feature(1_000)])
    persist.upsert_regime(
        con,
        "BTCUSDT",
        [(1_000, RegimeResult(RegimeLabel.RANGE, RegimeLabel.RANGE, 1.0, "range:ok"))],
    )
    row = con.execute(
        "SELECT f.ts, r.label FROM features f JOIN regime r ON f.ts=r.ts AND f.symbol=r.symbol"
    ).fetchone()
    assert row == (1_000, "RANGE")


def test_regime_upsert_updates_reason(tmp_path):
    con = _con(tmp_path)
    persist.upsert_regime(
        con, "BTCUSDT", [(1_000, RegimeResult(RegimeLabel.RANGE, RegimeLabel.RANGE, 1.0, "cu"))]
    )
    persist.upsert_regime(
        con,
        "BTCUSDT",
        [(1_000, RegimeResult(RegimeLabel.SQUEEZE, RegimeLabel.SQUEEZE, 1.0, "moi"))],
    )
    got = persist.read_regime(con, "BTCUSDT", 0, 2_000)
    assert len(got) == 1 and got[0]["label"] == "SQUEEZE" and got[0]["reason"] == "moi"


def test_regime_trend_dir_roundtrip(tmp_path):
    con = _con(tmp_path)
    up = RegimeResult(RegimeLabel.TREND, RegimeLabel.TREND, 1.0, "trend:ok", trend_dir=-1)
    persist.upsert_regime(con, "BTCUSDT", [(1_000, up)])
    assert persist.read_regime(con, "BTCUSDT", 0, 2_000)[0]["trend_dir"] == -1
    # upsert lai cung ts phai ghi de huong
    down = RegimeResult(RegimeLabel.TREND, RegimeLabel.TREND, 1.0, "trend:ok", trend_dir=1)
    persist.upsert_regime(con, "BTCUSDT", [(1_000, down)])
    got = persist.read_regime(con, "BTCUSDT", 0, 2_000)
    assert len(got) == 1 and got[0]["trend_dir"] == 1


def test_migration_adds_trend_dir_to_old_db(tmp_path):
    """DB tao truoc P1.2b (khong co cot trend_dir) phai duoc migrate, khong mat du lieu."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE regime(symbol TEXT NOT NULL, ts INTEGER NOT NULL, label TEXT NOT NULL,"
        " confidence REAL NOT NULL DEFAULT 0, raw_label TEXT NOT NULL,"
        " reason TEXT NOT NULL DEFAULT '', PRIMARY KEY(symbol, ts))"
    )
    old.execute(
        "INSERT INTO regime(symbol,ts,label,confidence,raw_label,reason)"
        " VALUES('BTCUSDT',1000,'RANGE',1.0,'RANGE','cu')"
    )
    old.commit()
    old.close()

    con = connect(str(path))  # connect() phai tu migrate
    cols = {r[1] for r in con.execute("PRAGMA table_info(regime)")}
    assert "trend_dir" in cols
    assert con.execute("SELECT trend_dir FROM regime").fetchone()[0] == 0
    assert con.execute("SELECT label FROM regime").fetchone()[0] == "RANGE"
    con.close()

    con2 = connect(str(path))  # idempotent, khong loi
    assert con2.execute("SELECT COUNT(*) FROM regime").fetchone()[0] == 1
    con2.close()
