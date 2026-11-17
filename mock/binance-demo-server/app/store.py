"""Luu tru SQLite: account, positions, orders, algo_orders, fills, income, events.

Tat ca so tien luu dang TEXT (Decimal) de khong mat precision.
"""
from __future__ import annotations

import sqlite3
import threading
from decimal import Decimal
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    wallet_balance  TEXT NOT NULL,
    initial_balance TEXT NOT NULL,
    updated_ms      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol          TEXT PRIMARY KEY,
    position_amt    TEXT NOT NULL DEFAULT '0',
    entry_price     TEXT NOT NULL DEFAULT '0',
    leverage        INTEGER NOT NULL DEFAULT 3,
    margin_type     TEXT NOT NULL DEFAULT 'isolated',
    isolated_wallet TEXT NOT NULL DEFAULT '0',
    realized_pnl    TEXT NOT NULL DEFAULT '0',
    updated_ms      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id        INTEGER PRIMARY KEY,
    client_order_id TEXT UNIQUE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    type            TEXT NOT NULL,
    orig_type       TEXT NOT NULL,
    time_in_force   TEXT,
    price           TEXT NOT NULL DEFAULT '0',
    stop_price      TEXT NOT NULL DEFAULT '0',
    orig_qty        TEXT NOT NULL DEFAULT '0',
    executed_qty    TEXT NOT NULL DEFAULT '0',
    avg_price       TEXT NOT NULL DEFAULT '0',
    status          TEXT NOT NULL,
    reduce_only     INTEGER NOT NULL DEFAULT 0,
    close_position  INTEGER NOT NULL DEFAULT 0,
    working_type    TEXT NOT NULL DEFAULT 'CONTRACT_PRICE',
    price_protect   INTEGER NOT NULL DEFAULT 0,
    created_ms      INTEGER NOT NULL,
    updated_ms      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS algo_orders (
    algo_id         INTEGER PRIMARY KEY,
    client_algo_id  TEXT UNIQUE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    type            TEXT NOT NULL,
    algo_type       TEXT NOT NULL DEFAULT 'CONDITIONAL',
    trigger_price   TEXT NOT NULL,
    working_type    TEXT NOT NULL DEFAULT 'CONTRACT_PRICE',
    price_protect   INTEGER NOT NULL DEFAULT 0,
    close_position  INTEGER NOT NULL DEFAULT 0,
    reduce_only     INTEGER NOT NULL DEFAULT 0,
    quantity        TEXT NOT NULL DEFAULT '0',
    status          TEXT NOT NULL,
    order_id        INTEGER,
    created_ms      INTEGER NOT NULL,
    updated_ms      INTEGER NOT NULL,
    trigger_ms      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fills (
    trade_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    price           TEXT NOT NULL,
    qty             TEXT NOT NULL,
    quote_qty       TEXT NOT NULL,
    fee             TEXT NOT NULL,
    fee_asset       TEXT NOT NULL DEFAULT 'USDT',
    maker           INTEGER NOT NULL DEFAULT 0,
    ts_ms           INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS income (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT,
    income_type     TEXT NOT NULL,
    income          TEXT NOT NULL,
    asset           TEXT NOT NULL DEFAULT 'USDT',
    ts_ms           INTEGER NOT NULL,
    tran_id         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms           INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    text            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seq (
    name            TEXT PRIMARY KEY,
    value           INTEGER NOT NULL
);
"""

POSITION_COLS = ("symbol", "position_amt", "entry_price", "leverage",
                 "margin_type", "isolated_wallet", "realized_pnl", "updated_ms")
ORDER_COLS = ("order_id", "client_order_id", "symbol", "side", "type", "orig_type",
              "time_in_force", "price", "stop_price", "orig_qty", "executed_qty",
              "avg_price", "status", "reduce_only", "close_position", "working_type",
              "price_protect", "created_ms", "updated_ms")
ALGO_COLS = ("algo_id", "client_algo_id", "symbol", "side", "type", "algo_type",
             "trigger_price", "working_type", "price_protect", "close_position",
             "reduce_only", "quantity", "status", "order_id", "created_ms",
             "updated_ms", "trigger_ms")


class Store:
    def __init__(self) -> None:
        self.conn: sqlite3.Connection | None = None
        self.lock = threading.RLock()
        self.path = ""

    # ------------------------------------------------------------ lifecycle

    def init(self, path: str, initial_balance: Decimal) -> None:
        with self.lock:
            if self.conn is not None:
                self.conn.close()
            self.path = path
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA)
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA foreign_keys=ON")
            row = self.conn.execute("SELECT COUNT(*) c FROM account").fetchone()
            if row["c"] == 0:
                import time
                self.conn.execute(
                    "INSERT INTO account(id, wallet_balance, initial_balance, updated_ms) VALUES(1,?,?,?)",
                    (str(initial_balance), str(initial_balance), int(time.time() * 1000)),
                )
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    # ------------------------------------------------------------ account

    def account(self) -> dict[str, Any]:
        with self.lock:
            r = self.conn.execute("SELECT * FROM account WHERE id=1").fetchone()
            return dict(r)

    def set_wallet(self, wallet: Decimal, ts_ms: int) -> None:
        with self.lock:
            self.conn.execute("UPDATE account SET wallet_balance=?, updated_ms=? WHERE id=1",
                              (str(wallet), ts_ms))
            self.conn.commit()

    # ------------------------------------------------------------ positions

    def positions(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
            return [dict(r) for r in rows]

    def position(self, symbol: str) -> dict[str, Any] | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            return dict(r) if r else None

    def upsert_position(self, p: dict[str, Any]) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO positions(" + ",".join(POSITION_COLS) + ") VALUES("
                + ",".join("?" * len(POSITION_COLS)) + ") "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "position_amt=excluded.position_amt, entry_price=excluded.entry_price, "
                "leverage=excluded.leverage, margin_type=excluded.margin_type, "
                "isolated_wallet=excluded.isolated_wallet, realized_pnl=excluded.realized_pnl, "
                "updated_ms=excluded.updated_ms",
                tuple(p[c] for c in POSITION_COLS),
            )
            self.conn.commit()

    # ------------------------------------------------------------ orders

    def next_id(self, name: str, start: int) -> int:
        with self.lock:
            r = self.conn.execute("SELECT value FROM seq WHERE name=?", (name,)).fetchone()
            if r is None:
                val = start
                self.conn.execute("INSERT INTO seq(name,value) VALUES(?,?)", (name, val))
            else:
                val = int(r["value"]) + 1
                self.conn.execute("UPDATE seq SET value=? WHERE name=?", (val, name))
            self.conn.commit()
            return val

    def insert_order(self, o: dict[str, Any]) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO orders(" + ",".join(ORDER_COLS) + ") VALUES("
                + ",".join("?" * len(ORDER_COLS)) + ")",
                tuple(o[c] for c in ORDER_COLS),
            )
            self.conn.commit()

    def update_order(self, order_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE orders SET {cols} WHERE order_id=?",
                              (*fields.values(), order_id))
            self.conn.commit()

    def order(self, order_id: int | None = None, client_id: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            if order_id is not None:
                r = self.conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            elif client_id:
                r = self.conn.execute("SELECT * FROM orders WHERE client_order_id=?", (client_id,)).fetchone()
            else:
                return None
            return dict(r) if r else None

    def orders(self, symbol: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM orders"
        cond, args = [], []
        if symbol:
            cond.append("symbol=?")
            args.append(symbol)
        if status:
            cond.append("status=?")
            args.append(status)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY order_id DESC"
        with self.lock:
            return [dict(r) for r in self.conn.execute(q, tuple(args)).fetchall()]

    # ------------------------------------------------------------ algo

    def insert_algo(self, a: dict[str, Any]) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO algo_orders(" + ",".join(ALGO_COLS) + ") VALUES("
                + ",".join("?" * len(ALGO_COLS)) + ")",
                tuple(a[c] for c in ALGO_COLS),
            )
            self.conn.commit()

    def update_algo(self, algo_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE algo_orders SET {cols} WHERE algo_id=?",
                              (*fields.values(), algo_id))
            self.conn.commit()

    def algo(self, algo_id: int | None = None, client_id: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            if algo_id is not None:
                r = self.conn.execute("SELECT * FROM algo_orders WHERE algo_id=?", (algo_id,)).fetchone()
            elif client_id:
                r = self.conn.execute("SELECT * FROM algo_orders WHERE client_algo_id=?",
                                      (client_id,)).fetchone()
            else:
                return None
            return dict(r) if r else None

    def algos(self, symbol: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM algo_orders"
        cond, args = [], []
        if symbol:
            cond.append("symbol=?")
            args.append(symbol)
        if status:
            cond.append("status=?")
            args.append(status)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY algo_id DESC"
        with self.lock:
            return [dict(r) for r in self.conn.execute(q, tuple(args)).fetchall()]

    # ------------------------------------------------------------ fills / income / events

    def insert_fill(self, f: dict[str, Any]) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO fills(order_id,symbol,side,price,qty,quote_qty,fee,fee_asset,maker,ts_ms)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f["order_id"], f["symbol"], f["side"], f["price"], f["qty"],
                 f["quote_qty"], f["fee"], f.get("fee_asset", "USDT"),
                 int(f.get("maker", 0)), f["ts_ms"]),
            )
            self.conn.commit()
            return int(cur.lastrowid or 0)

    def fills(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        q = "SELECT * FROM fills"
        args: tuple = ()
        if symbol:
            q += " WHERE symbol=?"
            args = (symbol,)
        q += " ORDER BY trade_id DESC LIMIT ?"
        with self.lock:
            return [dict(r) for r in self.conn.execute(q, (*args, limit)).fetchall()]

    def insert_income(self, symbol: str | None, income_type: str, income: Decimal,
                      ts_ms: int, asset: str = "USDT") -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO income(symbol,income_type,income,asset,ts_ms) VALUES(?,?,?,?,?)",
                (symbol, income_type, str(income), asset, ts_ms))
            self.conn.commit()

    def incomes(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM income ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def log_event(self, ts_ms: int, kind: str, text: str) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO events_log(ts_ms,kind,text) VALUES(?,?,?)",
                              (ts_ms, kind, text))
            self.conn.commit()

    def events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM events_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def state_hash(self) -> str:
        """Hash trang thai de test tinh tat dinh."""
        import hashlib
        h = hashlib.sha256()
        with self.lock:
            for table in ("account", "positions", "orders", "algo_orders", "fills"):
                h.update(table.encode())
                rows = self.conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for r in rows:
                    h.update(repr(tuple(r)).encode())
        return h.hexdigest()

    def counts(self) -> dict[str, int]:
        with self.lock:
            out = {}
            for table in ("account", "positions", "orders", "algo_orders", "fills", "income", "events_log"):
                out[table] = int(self.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"])
            return out

    def snapshot_to(self, path: str) -> str:
        """Ghi ban sao nhat quan ra file (dung VACUUM INTO, an toan khi dang chay)."""
        import os
        with self.lock:
            if os.path.exists(path):
                os.remove(path)
            self.conn.execute("VACUUM INTO ?", (path,))
            self.conn.commit()
        return path

    def restore_from(self, path: str) -> None:
        """Khoi phuc tu file snapshot: dong ket noi, ghi de, mo lai."""
        import os
        import shutil
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None
            if self.path not in (":memory:", ""):
                for suffix in ("", "-wal", "-shm"):
                    p = self.path + suffix
                    if os.path.exists(p):
                        os.remove(p)
                if os.path.exists(self.path) and os.path.abspath(path) == os.path.abspath(self.path):
                    raise ValueError("snapshot trung voi db hien tai")
                shutil.copyfile(path, self.path)
            target = self.path if self.path not in ("", ":memory:") else path
            self.init(target, __import__("decimal").Decimal("0"))


STORE = Store()
