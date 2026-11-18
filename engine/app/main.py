"""Main P1.3: config + adapter + reconcile + command loop + market poll.

Chua co chien luoc (P1.4). Muc tieu cua P1.3 la ha tang an toan: moi lenh qua risk,
SL luon ton tai, kill switch phan hoi < 2s, restart khong mat state.
"""

from __future__ import annotations

import os
import threading
import time

from . import config as config_mod
from .db.store import connect, get_state
from .exchange import clock as clock_mod
from .exchange import orders as orders_mod
from .exchange import reconcile as reconcile_mod
from .exchange import rest as rest_mod
from .exchange import ws as ws_mod
from .exec import recovery
from .exec.executor import Executor
from .ops import alert as alert_mod
from .ops import commands as commands_mod
from .ops.log import log

HB = "/app/data/heartbeat"
RECONCILE_S = 5.0
MARKET_S = 2.0  # < stale 3s: poll REST de last_market_ms luon tuoi (WS market la P1.6)


def build(cfg=None, rest_client=None, db_path: str | None = None) -> dict:
    cfg = cfg or config_mod.load()
    base = os.environ.get("BINANCE_BASE_URL", cfg.base_url)
    ws_base = os.environ.get("BINANCE_WS_URL", cfg.ws_url)
    api_key = os.environ.get("BINANCE_API_KEY") or os.environ.get("MOCK_API_KEY", "verify-key")
    secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get(
        "MOCK_API_SECRET", "mock-secret"
    )
    db_path = db_path or os.environ.get("DB_PATH") or cfg.ops.get("db_path") or "/app/data/bot.db"
    rest = rest_client or rest_mod.RestClient(base, api_key, secret)
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
    ex = Executor(con, rest, cfg, mgr=mgr)
    return {
        "cfg": cfg,
        "rest": rest,
        "con": con,
        "alerter": alerter,
        "mgr": mgr,
        "rec": rec,
        "ex": ex,
        "ws_base": ws_base,
    }


def on_user(mgr: orders_mod.OrderManager, con, ev: dict) -> None:
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


def market_loop(ex: Executor, symbols: list[str], stop: threading.Event) -> None:
    """Poll bookTicker de co last_market_ms + spread (WS market chua co o P1.3)."""
    while not stop.wait(MARKET_S):
        for sym in symbols[:1]:
            try:
                ex.refresh_market(sym)
            except Exception as e:
                log("warn", "market.poll_fail", error=str(e)[:150])


def main() -> None:
    ctx = build()
    cfg = ctx["cfg"]
    con = ctx["con"]
    ex = ctx["ex"]
    stop = threading.Event()

    try:
        rep = recovery.recover(con, ctx["rest"], cfg, ex=ex)
        log("info", "engine.recovery", **rep)
        if rep.get("halted"):
            ctx["alerter"].push("recovery", f"Recovery phat hien lech: {rep}")
    except Exception as e:
        log("error", "engine.recovery_fail", error=str(e)[:200])

    threading.Thread(target=heartbeat_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=reconcile_loop, args=(ctx["rec"], stop), daemon=True).start()
    threading.Thread(target=commands_mod.run_loop, args=(con, ex, stop), daemon=True).start()
    symbols = list(cfg.universe.get("symbols") or ["BTCUSDT"])
    threading.Thread(target=market_loop, args=(ex, symbols, stop), daemon=True).start()

    keeper = ws_mod.ListenKeyKeeper(ctx["rest"])
    url_base = ctx["ws_base"]
    conn = ws_mod.WsConnection(
        "user",
        lambda: url_base.rstrip("/") + "/ws/" + keeper.ensure(),
        lambda ev: on_user(ctx["mgr"], con, ev),
    )
    keeper.start()
    conn.start()
    log(
        "info",
        "engine.start",
        env=cfg.env,
        halted=get_state(con, "halted", "0"),
        paused=get_state(con, "paused", "0"),
    )
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        conn.stop()
        keeper.stop()


if __name__ == "__main__":
    main()
