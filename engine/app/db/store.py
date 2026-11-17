"""SQLite writer duy nhat. WAL + busy_timeout=5000 (AGENTS.md §7)."""

from __future__ import annotations

import sqlite3

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL,
  exchange_id TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL, type TEXT NOT NULL,
  qty TEXT NOT NULL, price TEXT, status TEXT NOT NULL DEFAULT 'NEW',
  created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_ref TEXT NOT NULL,
  symbol TEXT NOT NULL, side TEXT NOT NULL, qty TEXT NOT NULL,
  price TEXT NOT NULL, fee TEXT DEFAULT '0', ts_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS positions(
  symbol TEXT PRIMARY KEY, amt TEXT NOT NULL DEFAULT '0',
  entry TEXT DEFAULT '0', updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runtime_state(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
  payload TEXT NOT NULL, ts_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
  detail TEXT NOT NULL, ts_ms INTEGER NOT NULL);
"""


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: WS thread ghi, reconcile thread doc (main.py).
    con = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    for stmt in [s for s in SCHEMA.split(";") if s.strip() and not s.strip().startswith("PRAGMA")]:
        con.execute(stmt)
    return con


def set_state(con: sqlite3.Connection, key: str, value: str, now_ms: int) -> None:
    con.execute(
        "INSERT INTO runtime_state(key,value,updated_ms) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_ms=excluded.updated_ms",
        (key, value, now_ms),
    )


def get_state(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else default
