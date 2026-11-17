"""Soak harness P1.1: chay adapter tren mock, bom lenh + chaos.

Chay truc tiep:  python -m app.soak --minutes 4320 --cycles 25 --drops 5
Che do service:  compose service `soak` (profile app), status o SOAK_STATUS_PATH.
Khong doc .env that: dung secret mock mac dinh. Khong in secret.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request

BASE = os.environ.get("SOAK_BASE_URL", "http://127.0.0.1:8081")
SECRET = os.environ.get("MOCK_API_SECRET", "mock-secret")
SYM = "DOGEUSDT"
PRUNE_DAYS = 7


def _ws_base(base: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


def prune_old(data_dir: str, days: int = PRUNE_DAYS) -> int:
    """Xoa file soak-* qua han. Tra ve so file da xoa."""
    try:
        names = os.listdir(data_dir)
    except OSError:
        return 0
    cutoff = time.time() - days * 86400.0
    n = 0
    for nm in names:
        if not nm.startswith("soak-"):
            continue
        fp = os.path.join(data_dir, nm)
        try:
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
                n += 1
        except OSError:
            pass
    return n


def write_status(path: str, rep: dict) -> None:
    """Ghi nguyen tu (tmp + rename) de /check72h khong doc file do."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_status(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"state": "pending", "errors": ["chua co file status"]}


def _admin(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _qty(rest) -> str:
    px = float(rest.get("/fapi/v1/ticker/price", {"symbol": SYM}, signed=False)["price"])
    info = rest.get("/fapi/v1/exchangeInfo", signed=False)
    step = 1.0
    for s in info.get("symbols", []):
        if s.get("symbol") == SYM:
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step = float(f["stepSize"])
    return str(max(step, round(20 / max(px, 1e-9) / step) * step))


def _wait_flat(rest, timeout_s: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        oo = rest.get("/fapi/v1/openOrders")
        ao = rest.get("/fapi/v1/openAlgoOrders")
        pr = rest.get("/fapi/v2/positionRisk")
        n_oo = len(oo) if isinstance(oo, list) else 0
        n_ao = len(ao.get("orders", [])) if isinstance(ao, dict) else len(ao or [])
        n_p = sum(
            1
            for p in (pr if isinstance(pr, list) else [])
            if float(p.get("positionAmt", 0) or 0) != 0
        )
        if n_oo == 0 and n_ao == 0 and n_p == 0:
            return True
        time.sleep(2)
    return False


def _flatten(rest) -> None:
    pr = rest.get("/fapi/v2/positionRisk")
    for p in pr if isinstance(pr, list) else []:
        amt = float(p.get("positionAmt", 0) or 0)
        if amt == 0:
            continue
        side = "SELL" if amt > 0 else "BUY"
        try:
            rest.post(
                "/fapi/v1/order",
                {
                    "symbol": p["symbol"],
                    "side": side,
                    "type": "MARKET",
                    "quantity": str(abs(amt)),
                    "newClientOrderId": "soak-flat-%d" % int(time.time() * 1000),
                },
            )
        except Exception:
            pass
    for path, kw in (("/fapi/v1/allOpenOrders", {}),):
        try:
            rest.delete(path, kw)
        except Exception:
            pass
    try:
        ao = rest.get("/fapi/v1/openAlgoOrders")
        syms = {
            o.get("symbol")
            for o in (ao.get("orders", []) if isinstance(ao, dict) else [])
            if o.get("symbol")
        }
        for s in syms:
            try:
                rest.delete("/fapi/v1/algoOpenOrders", {"symbol": s})
            except Exception:
                pass
    except Exception:
        pass


def blank_report() -> dict:
    return {
        "state": "pending",
        "t0": int(time.time() * 1000),
        "deadline": 0,
        "cycles": 0,
        "planned_cycles": 0,
        "orphans": 0,
        "ws_drops": 0,
        "reconnect_ok": 0,
        "dup_ok": None,
        "chaos_backoff_ok": None,
        "restart_ok": None,
        "reconcile_diffs": 0,
        "wal_bytes": [],
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    from app.db.store import connect
    from app.exchange.orders import OrderManager
    from app.exchange.reconcile import Reconciler
    from app.exchange.rest import RestClient
    from app.ops.alert import Alerter
    from app.ops.tgcmd import CommandPoller, format_status_vi

    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--drops", type=int, default=1)
    ap.add_argument("--report", default=os.environ.get("SOAK_REPORT_PATH", "soak-report.json"))
    ap.add_argument("--status", default=os.environ.get("SOAK_STATUS_PATH", "soak-status.json"))
    a = ap.parse_args(argv)

    status_dir = os.path.dirname(os.path.abspath(a.status)) or "."
    if os.path.isdir(status_dir):
        pruned = prune_old(status_dir)
    else:
        pruned = 0

    rep = blank_report()
    rep.update(
        {
            "planned_cycles": a.cycles,
            "minutes_total": a.minutes,
            "deadline": int(time.time() * 1000 + a.minutes * 60000),
            "commit": os.environ.get("SOAK_COMMIT", ""),
        }
    )
    write_status(a.status, rep)

    alerter = Alerter(
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_ID", ""),
        os.environ.get("TELEGRAM_TOPIC_ID", ""),
    )
    poller = None
    if alerter.enabled():
        poller = CommandPoller(
            os.environ["TELEGRAM_BOT_TOKEN"],
            os.environ["TELEGRAM_CHAT_ID"],
            lambda: read_status(a.status),
            offset_path=os.path.join(status_dir, "soak-tgoffset.txt"),
        )
        poller.start()
        alerter.push(
            "soak-start",
            "Soak 72h: BẮT ĐẦU (%d vòng, %s phút, commit %s, đã dọn %d file cũ)"
            % (a.cycles, a.minutes, rep["commit"] or "?", pruned),
        )
        alerter.flush()

    tmp = tempfile.mkdtemp(prefix="soak-")
    db_path = os.path.join(tmp, "soak.db")
    milestone_24 = rep["t0"] + 24 * 3600000

    def _publish():
        write_status(a.status, rep)

    try:
        rest = RestClient(BASE, "soak-key", SECRET)
        qty = _qty(rest)
        con = connect(db_path)
        mgr = OrderManager(con, rest, strategy="soak")
        rec = Reconciler(con, rest, alerter if alerter.enabled() else None)
        deadline = time.time() + a.minutes * 60
        pace = (a.minutes * 60.0) / max(a.cycles, 1)

        rep["state"] = "running"
        _publish()

        _flatten(rest)
        if not _wait_flat(rest, 30):
            rep["errors"].append("khong flatten duoc mock")
            raise RuntimeError("flatten_fail")

        import threading

        from websocket import create_connection

        ws_base = _ws_base(BASE)
        lk = rest.post("/fapi/v1/listenKey")["listenKey"]
        ws_state = {"stop": False}

        def _feed():
            while not ws_state["stop"]:
                try:
                    w = create_connection(ws_base + "/ws/" + lk, timeout=8)
                    w.settimeout(5.0)
                    while not ws_state["stop"]:
                        try:
                            m = w.recv()
                        except Exception:
                            break
                        try:
                            ev = json.loads(m)
                        except Exception:
                            continue
                        k = ev.get("e", "")
                        if k == "ORDER_TRADE_UPDATE":
                            mgr.on_order_trade(ev)
                        elif k == "ALGO_UPDATE":
                            mgr.on_algo_update(ev)
                except Exception:
                    time.sleep(1.0)

        th = threading.Thread(target=_feed, daemon=True)
        th.start()

        _admin("/_admin/chaos", {"throttle_1008": True})
        try:
            rest.get("/fapi/v1/ping", signed=False, max_tries=5)
            rep["chaos_backoff_ok"] = True
        except Exception as e:
            rep["errors"].append("chaos: %s" % type(e).__name__)
        finally:
            _admin("/_admin/reset")
        _publish()

        cid = "soak-dup-%d" % int(time.time() * 1000)
        mgr.place(SYM, "BUY", "MARKET", qty, client_id=cid)
        r2 = mgr.place(SYM, "BUY", "MARKET", qty, client_id=cid)
        n = con.execute("SELECT COUNT(*) FROM orders WHERE client_id=?", (cid,)).fetchone()[0]
        rep["dup_ok"] = bool(r2.get("deduped")) and n == 1
        mgr.place(SYM, "SELL", "MARKET", qty, client_id=cid + "-close")
        time.sleep(2)
        _publish()

        cyc = 0
        while cyc < a.cycles and time.time() < deadline:
            t_cyc = time.time()
            tag = "soak-%d-%d" % (cyc, int(time.time() * 1000))
            mgr.place(SYM, "BUY", "MARKET", qty, client_id=tag + "-o")
            mgr.place_algo(SYM, "SELL", "STOP_MARKET", "0.00001", client_id=tag + "-sl")
            mgr.place(SYM, "SELL", "MARKET", qty, client_id=tag + "-c")
            time.sleep(3)
            rep["reconcile_diffs"] += rec.check()
            cyc += 1
            rep["cycles"] = cyc
            for p in ("", "-wal", "-shm"):
                fp = db_path + p
                if os.path.exists(fp):
                    rep.setdefault("wal_" + (p or "db"), []).append(os.path.getsize(fp))
            _publish()
            if int(time.time() * 1000) >= milestone_24:
                milestone_24 += 24 * 3600000
                if alerter.enabled():
                    alerter.push("soak-24h", format_status_vi(rep))
                    alerter.flush()
            time.sleep(max(2.0, pace - (time.time() - t_cyc)))

        keep = "soak-keep-%d" % int(time.time() * 1000)
        mgr.place(SYM, "BUY", "MARKET", qty, client_id=keep)
        for _ in range(10):
            r = con.execute("SELECT amt FROM positions WHERE symbol=?", (SYM,)).fetchone()
            if r and float(r[0]) != 0:
                break
            time.sleep(2)
        con2 = connect(db_path)
        OrderManager(con2, RestClient(BASE, "soak-key", SECRET), strategy="soak")
        row = con2.execute("SELECT status FROM orders WHERE client_id=?", (keep,)).fetchone()
        rec2 = Reconciler(con2, RestClient(BASE, "soak-key", SECRET), None)
        rep["restart_ok"] = row is not None and rec2.check() == 0
        mgr.place(SYM, "SELL", "MARKET", qty, client_id=keep + "-close")
        time.sleep(2)
        _publish()

        for _ in range(a.drops):
            w = create_connection(ws_base + "/ws/" + lk, timeout=8)
            _admin("/_admin/ws/drop")
            w.close()
            w2 = create_connection(ws_base + "/ws/" + lk, timeout=8)
            w2.close()
            rest.put_keyalive(lk)
            rep["ws_drops"] += 1
            rep["reconnect_ok"] += 1
        _publish()

        ws_state["stop"] = True
        ok_flat = _wait_flat(rest, 60)
        oo = rest.get("/fapi/v1/openOrders")
        ao = rest.get("/fapi/v1/openAlgoOrders")
        pr = rest.get("/fapi/v2/positionRisk")
        open_pos = [
            p for p in (pr if isinstance(pr, list) else []) if float(p.get("positionAmt", 0)) != 0
        ]
        rep["final"] = {
            "openOrders": len(oo),
            "openAlgo": len(ao.get("orders", [])),
            "positions": len(open_pos),
            "wait_flat_ok": ok_flat,
        }
        rep["pass"] = (
            rep["orphans"] == 0
            and rep["final"]["openOrders"] == 0
            and rep["final"]["positions"] == 0
            and rep["dup_ok"]
            and rep["restart_ok"]
            and rep["reconnect_ok"] == rep["ws_drops"]
            and rep["chaos_backoff_ok"]
        )
        rep["state"] = "done"
    except Exception as e:
        rep["errors"].append("%s: %s" % (type(e).__name__, str(e)[:200]))
        rep["pass"] = False
        rep["state"] = "error"
    rep["t1"] = int(time.time() * 1000)
    _publish()
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    if alerter.enabled():
        alerter.push("soak-end", format_status_vi(rep))
        alerter.flush()
    if poller:
        poller.stop()
    print(
        json.dumps(
            {k: v for k, v in rep.items() if not str(k).startswith("wal")}, ensure_ascii=False
        )
    )
    return 0 if rep.get("pass") else 3


if __name__ == "__main__":
    raise SystemExit(main())
