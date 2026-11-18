"""Test P1.2 replay: tat dinh, hash canonical, khong doc dong ho, persist."""

from __future__ import annotations

import inspect
import json
import random
from datetime import date

from app.data import parquet_io
from app.data import replay as R

START = 1_767_225_600_000  # 2026-01-01T00:00Z, chia het 15m
M15 = 15 * 60_000


def bars15(n: int = 800, *, seed: int = 3, drift: float = 0.15, noise: float = 1.0) -> list[dict]:
    rnd = random.Random(seed)
    out, prev = [], 100.0
    for i in range(n):
        c = 100 + drift * i + rnd.uniform(-noise, noise)
        out.append(
            {
                "open_time": START + i * M15,
                "close_time": START + i * M15 + M15 - 1,
                "o": prev,
                "h": max(prev, c) + 0.5,
                "l": min(prev, c) - 0.5,
                "c": c,
                "v": 10.0 + i % 7,
                "closed": True,
            }
        )
        prev = c
    return out


def run(bars: list[dict]) -> R.ReplayOutput:
    return R.run_bars("BTCUSDT", bars, bbw_min_samples=5, vol_min_samples=5)


def test_two_runs_same_hash():
    bars = bars15()
    a, b = run(bars), run(list(bars))
    assert a.hash == b.hash and a.raw_hash == b.raw_hash
    assert a.report == b.report


def test_changing_one_bar_changes_hash():
    bars = bars15()
    base = run(bars).hash
    bars[-1]["c"] = bars[-1]["c"] + 1.0
    assert run(bars).hash != base


def test_report_json_is_stable_and_written_same(tmp_path):
    out = run(bars15())
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    R.write_report(out, str(p1))
    R.write_report(out, str(p2))
    assert p1.read_bytes() == p2.read_bytes()
    rep = json.loads(p1.read_text(encoding="utf-8"))
    assert rep == out.report
    assert list(rep) == sorted(rep)  # sort_keys


def test_canonical_line_formats_none_and_floats():
    f = {"atr": 1.0, "adx": 2.0, "bbw": 0.25, "bbw_pct": None, "z": -1.5, "vol_pct": 50.0}
    line = R.canonical_line(123, "RANGE", 1.0, f)
    ts, label, conf, atr, adx, bbw, bbwp, z, volp = line.split(",")
    assert (ts, label, conf) == ("123", "RANGE", "1.0000")
    assert (atr, adx, bbw) == ("1.0000000000", "2.0000000000", "0.2500000000")
    assert bbwp == "-" and z == "-1.5000000000" and volp == "50.0000000000"
    assert R.canonical_line(1, "UNKNOWN", 0.0, None) == "1,UNKNOWN,0.0000,-,-,-,-,-,-"


def test_counts_cover_all_bars_and_transitions_bounded():
    out = run(bars15(500))
    assert sum(out.label_counts.values()) == 500
    assert sum(out.raw_counts.values()) == 500
    assert 0 <= out.transitions <= 499 and 0 <= out.raw_transitions <= 499
    assert out.report["bars"] == 500 and out.report["hash"] == out.hash


def test_replay_module_has_no_wall_clock():
    src = inspect.getsource(R)
    assert "import time" not in src
    assert "datetime.now" not in src and "time.time" not in src


def _write_1m_day(root, symbol: str, day: date, n: int = 1440) -> None:
    start = int(day.toordinal() * 86_400_000)  # moc ngay UTC gia lap
    bars = [
        {
            "open_time": start + i * 60_000,
            "close_time": start + i * 60_000 + 59_999,
            "o": 100.0 + i * 0.001,
            "h": 100.0 + i * 0.001 + 0.05,
            "l": 100.0 + i * 0.001 - 0.05,
            "c": 100.0 + i * 0.001 + 0.02,
            "v": 5.0,
            "closed": True,
        }
        for i in range(n)
    ]
    parquet_io.save_day(root, symbol, "1m", day.isoformat(), bars)


def test_replay_symbol_reads_parquet_persists_and_reports(tmp_path):
    root = str(tmp_path / "market")
    d = date(2026, 6, 1)
    _write_1m_day(root, "BTCUSDT", d)
    db = str(tmp_path / "p12.db")
    out = R.replay_symbol("BTCUSDT", d, d, root=root, db_path=db)
    assert out.report["bars"] == 96
    assert len(out.report["data_files_sha256"]) == 64
    import sqlite3

    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 96
    assert con.execute("SELECT COUNT(*) FROM regime").fetchone()[0] == 96
    assert con.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 68  # warmup 28 nen
    con.close()


def test_data_sha256_changes_when_partition_changes(tmp_path):
    root = str(tmp_path / "market")
    d = date(2026, 6, 1)
    _write_1m_day(root, "BTCUSDT", d)
    a = R.data_sha256(root, "BTCUSDT", [d.isoformat()])
    b = R.data_sha256(root, "BTCUSDT", [d.isoformat()])
    assert a == b
    _write_1m_day(root, "BTCUSDT", d, n=1439)
    assert R.data_sha256(root, "BTCUSDT", [d.isoformat()]) != a
