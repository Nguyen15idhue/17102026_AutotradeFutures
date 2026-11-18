"""Integration P1.3 tren mock: fill -> SL, close -> 0 orphan, kill switch < 2s.

Chay trong container engine, mock dang bat, va KHONG chay main engine cung luc
(script p1.3-check.ps1 se stop engine truoc) de tranh reconcile HALT oan.
In dung 1 dong JSON de script PS parse tiet kiem token.
"""

from __future__ import annotations

import json
import os
import sys
import time

from .. import config as config_mod
from ..db import store
from ..exchange import rest as rest_mod
from ..exec.executor import Executor
from ..ops import commands
from ..risk.types import OrderRequest


def _build():
    cfg = config_mod.load()
    if cfg.env != "mock":
        raise SystemExit("integration chi chay tren mock")
    key = os.environ.get("MOCK_API_KEY", "verify-key")
    secret = os.environ.get("MOCK_API_SECRET", "mock-secret")
    rest = rest_mod.RestClient(cfg.base_url, key, secret)
    con = store.connect(os.environ.get("DB_PATH", "/app/data/bot.db"))
    ex = Executor(con, rest, cfg)
    # Harness: don vi the cu + bo halt/pause de lan chay sau khong bi chan oan.
    for (sym,) in con.execute(
        "SELECT symbol FROM positions WHERE state='OPEN' AND CAST(amt AS REAL) != 0"
    ).fetchall():
        try:
            ex.close(str(sym), "integration_reset")
        except Exception:
            pass
    now = int(time.time() * 1000)
    for key_, val in (("halted", "0"), ("paused", "0")):
        con.execute(
            "INSERT INTO runtime_state(key,value,updated_ms) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_ms=excluded.updated_ms",
            (key_, val, now),
        )
    # Don lenh cua harness (manual/sys) de khong cham max_orders_per_day khi chay lap.
    con.execute("DELETE FROM fills WHERE order_ref LIKE 'manual-%' OR order_ref LIKE 'sys-%'")
    con.execute("DELETE FROM orders WHERE client_id LIKE 'manual-%' OR client_id LIKE 'sys-%'")
    return cfg, con, rest, ex


def _open(ex: Executor, cfg, symbol: str = "BTCUSDT") -> dict:
    m = ex.refresh_market(symbol)
    entry = m["ask"]
    req = OrderRequest(
        strategy_id="manual",
        symbol=symbol,
        side="BUY",
        entry=entry,
        stop=entry * (1 - 80 / 10_000),
        tp=entry * (1 + 150 / 10_000),
        order_type="market",
        meta={"risk_usd": cfg.risk.risk_per_trade * cfg.equity_base},
    )
    return ex.open(req)


def _open_algos(rest, symbol: str) -> list[dict]:
    rows = rest.get("/fapi/v1/openAlgoOrders")
    # Binance/mock tra {"total": n, "orders": [...]}; mot so ban cu tra list.
    items = rows.get("orders", []) if isinstance(rows, dict) else rows
    return [
        a
        for a in (items if isinstance(items, list) else [])
        if str(a.get("symbol")) == symbol
        and str(a.get("algoStatus", "")).upper() not in ("CANCELED", "EXPIRED", "FINISHED")
    ]


def open_close() -> dict:
    cfg, con, rest, ex = _build()
    sym = "BTCUSDT"
    r = _open(ex, cfg, sym)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason")}
    algos_after_open = len(_open_algos(rest, sym))
    c = ex.close(sym, "integration")
    algos_after_close = len(_open_algos(rest, sym))
    con.close()
    return {
        "ok": bool(c.get("ok")),
        "sl_latency_ms": r.get("sl_latency_ms"),
        "algos_after_open": algos_after_open,
        "orphan_after_close": algos_after_close,
        "close_ok": bool(c.get("ok")),
    }


def killswitch() -> dict:
    cfg, con, rest, ex = _build()
    sym = "BTCUSDT"
    r = _open(ex, cfg, sym)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason")}
    commands.enqueue(con, "stop")
    t0 = time.monotonic()
    commands.handle_once(con, ex)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    amt, state = con.execute("SELECT amt, state FROM positions WHERE symbol=?", (sym,)).fetchone()
    halted = con.execute("SELECT value FROM runtime_state WHERE key='halted'").fetchone()
    con.close()
    return {
        "ok": state == "CLOSED" and float(amt) == 0.0,
        "kill_ms": elapsed_ms,
        "halted": bool(halted and halted[0] == "1"),
        "orphan_after_stop": len(_open_algos(rest, sym)),
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "open-close"
    out = killswitch() if mode == "killswitch" else open_close()
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
