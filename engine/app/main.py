"""Main P1.1: REST + user WS + reconcile 5s + heartbeat. Chua co chien luoc.

FE: khong ap dung (engine la backend thuan).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

from .db.store import connect, get_state
from .exchange import clock as clock_mod
from .exchange import orders as orders_mod
from .exchange import reconcile as reconcile_mod
from .exchange import rest as rest_mod
from .exchange import ws as ws_mod
from .ops import alert as alert_mod
from .ops.log import log

HB = "/app/data/heartbeat"
RECONCILE_S = 5.0


def build() -> dict:
    base = os.environ.get("BINANCE_BASE_URL", "http://binance-demo-server:8080")
    ws_base = os.environ.get("BINANCE_WS_URL", "ws://binance-demo-server:8080")
    api_key = os.environ.get("BINANCE_API_KEY") or os.environ.get("MOCK_API_KEY", "verify-key")
    secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get(
        "MOCK_API_SECRET", "mock-secret"
    )
    db_path = os.environ.get("DB_PATH", "/app/data/bot.db")
    rest = rest_mod.RestClient(base, api_key, secret)
    try:  # clock offset truoc phien (NTP co the troi)
        off = clock_mod.measure_offset(
            lambda: rest.get("/fapi/v1/time", signed=False)["serverTime"]
        )
        rest.offset_ms = off
        log("info", "clock.sync", offset_ms=off)
    except Exception as e:
        log("warn", "clock.sync_fail", error=str(e)[:150])
    con = connect(db_path)
    alerter = alert_mod.Alerter(
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_ID", ""),
        os.environ.get("TELEGRAM_TOPIC_ID", ""),
    )
    mgr = orders_mod.OrderManager(con, rest)
    rec = reconcile_mod.Reconciler(con, rest, alerter)
    return {
        "rest": rest,
        "con": con,
        "alerter": alerter,
        "mgr": mgr,
        "rec": rec,
        "ws_base": ws_base,
    }


def on_user(mgr: orders_mod.OrderManager, con: sqlite3.Connection, ev: dict) -> None:
    kind = ws_mod.route_user_event(ev)
    if kind == "ORDER_TRADE_UPDATE":
        mgr.on_order_trade(ev)
    elif kind == "ALGO_UPDATE":
        mgr.on_algo_update(ev)
    con.execute(
        "INSERT INTO events(kind,payload,ts_ms) VALUES(?,?,?)",
        (kind, str(ev)[:2000], int(time.time() * 1000)),
    )


def heartbeat_loop(stop: threading.Event) -> None:
    os.makedirs(os.path.dirname(HB), exist_ok=True)
    while not stop.wait(10):
        with open(HB, "w", encoding="utf-8") as f:
            f.write(str(int(time.time() * 1000)))


def reconcile_loop(rec: reconcile_mod.Reconciler, stop: threading.Event) -> None:
    while not stop.wait(RECONCILE_S):
        try:
            rec.check()
        except Exception as e:
            log("warn", "reconcile.error", error=str(e)[:150])


def main() -> None:
    ctx = build()
    stop = threading.Event()
    threading.Thread(target=heartbeat_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=reconcile_loop, args=(ctx["rec"], stop), daemon=True).start()
    keeper = ws_mod.ListenKeyKeeper(ctx["rest"])
    url_base = ctx["ws_base"]
    conn = ws_mod.WsConnection(
        "user",
        lambda: url_base.rstrip("/") + "/ws/" + keeper.ensure(),
        lambda ev: on_user(ctx["mgr"], ctx["con"], ev),
    )
    keeper.start()
    conn.start()
    log("info", "engine.start", halted=get_state(ctx["con"], "halted", "0"))
    try:
        while True:
            time.sleep(30)  # user stream im lang khi khong co lenh la binh thuong;
            # stale >3s chi ap dung cho market data (P1.2), khong canh bao o day.
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        conn.stop()
        keeper.stop()


if __name__ == "__main__":
    main()
