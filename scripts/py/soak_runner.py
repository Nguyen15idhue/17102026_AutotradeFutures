"""Soak harness P1.1: chay adapter tren mock, bom lenh + chaos, ghi soak-report.json.

Full 72h (VPS, phien sau): python scripts/py/soak_runner.py --minutes 4320 --cycles 25 --drops 5
Smoke local (phien nay):    python scripts/py/soak_runner.py --minutes 10 --cycles 3 --drops 1
Khong doc .env that: dung secret mock mac dinh. Khong in secret.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from app.db.store import connect  # noqa: E402
from app.exchange.orders import OrderManager  # noqa: E402
from app.exchange.reconcile import Reconciler  # noqa: E402
from app.exchange.rest import RestClient  # noqa: E402

BASE = os.environ.get("SOAK_BASE_URL", "http://127.0.0.1:8081")
SECRET = os.environ.get("MOCK_API_SECRET", "mock-secret")
SYM = "DOGEUSDT"


def _admin(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _qty(rest: RestClient) -> str:
    px = float(rest.get("/fapi/v1/ticker/price", {"symbol": SYM}, signed=False)["price"])
    info = rest.get("/fapi/v1/exchangeInfo", signed=False)
    step = 1.0
    for s in info.get("symbols", []):
        if s.get("symbol") == SYM:
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step = float(f["stepSize"])
    return str(max(step, round(20 / max(px, 1e-9) / step) * step))


def _wait_flat(rest: RestClient, timeout_s: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        oo = rest.get("/fapi/v1/openOrders")
        ao = rest.get("/fapi/v1/openAlgoOrders")
        pr = rest.get("/fapi/v2/positionRisk")
        n_oo = len(oo) if isinstance(oo, list) else 0
        n_ao = len(ao.get("orders", [])) if isinstance(ao, dict) else len(ao or [])
        n_p = sum(1 for p in (pr if isinstance(pr, list) else [])
                  if float(p.get("positionAmt", 0) or 0) != 0)
        if n_oo == 0 and n_ao == 0 and n_p == 0:
            return True
        time.sleep(2)
    return False


def _flatten(rest: RestClient) -> None:
    pr = rest.get("/fapi/v2/positionRisk")
    for p in (pr if isinstance(pr, list) else []):
        amt = float(p.get("positionAmt", 0) or 0)
        if amt == 0:
            continue
        side = "SELL" if amt > 0 else "BUY"
        try:
            rest.post("/fapi/v1/order", {"symbol": p["symbol"], "side": side,
                                         "type": "MARKET", "quantity": str(abs(amt)),
                                         "newClientOrderId": "soak-flat-%d" % int(time.time() * 1000)})
        except Exception:
            pass
    try:
        rest.delete("/fapi/v1/allOpenOrders")
    except Exception:
        pass
    try:
        ao = rest.get("/fapi/v1/openAlgoOrders")
        syms = {o.get("symbol") for o in (ao.get("orders", []) if isinstance(ao, dict) else []) if o.get("symbol")}
        for s in syms:
            try:
                rest.delete("/fapi/v1/algoOpenOrders", {"symbol": s})
            except Exception:
                pass
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--drops", type=int, default=1)
    ap.add_argument("--report", default="soak-report.json")
    a = ap.parse_args()

    rep: dict = {"t0": int(time.time() * 1000), "cycles": 0, "orphans": 0,
                 "ws_drops": 0, "reconnect_ok": 0, "dup_ok": False,
                 "chaos_backoff_ok": False, "restart_ok": False,
                 "reconcile_diffs": 0, "wal_bytes": [], "errors": []}
    tmp = tempfile.mkdtemp(prefix="soak-")
    db_path = os.path.join(tmp, "soak.db")

    try:
        rest = RestClient(BASE, "soak-key", SECRET)
        qty = _qty(rest)
        con = connect(db_path)
        mgr = OrderManager(con, rest, strategy="soak")
        rec = Reconciler(con, rest, None)
        deadline = time.time() + a.minutes * 60

        # 0) flatten: dong moi position, huy moi algo -> bat dau phang
        _flatten(rest)
        if not _wait_flat(rest, 30):
            rep["errors"].append("khong flatten duoc mock")
            raise RuntimeError("flatten_fail")

        # 0b) WS user stream: feed event that vao manager (nhu main.py)
        import threading
        from websocket import create_connection

        lk = rest.post("/fapi/v1/listenKey")["listenKey"]
        ws_state = {"stop": False}

        def _feed():
            while not ws_state["stop"]:
                try:
                    w = create_connection("ws://127.0.0.1:8081/ws/" + lk, timeout=8)
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

        # 1) chaos throttle_1008 -> client phai backoff, khong spam chet
        _admin("/_admin/chaos", {"throttle_1008": True})
        try:
            rest.get("/fapi/v1/ping", signed=False, max_tries=5)
            rep["chaos_backoff_ok"] = True
        except Exception as e:
            rep["errors"].append("chaos: %s" % type(e).__name__)
        finally:
            _admin("/_admin/reset")

        # 2) trung clientOrderId -> khong tao lenh 2
        cid = "soak-dup-%d" % int(time.time() * 1000)
        mgr.place(SYM, "BUY", "MARKET", qty, client_id=cid)
        r2 = mgr.place(SYM, "BUY", "MARKET", qty, client_id=cid)
        n = con.execute(
            "SELECT COUNT(*) FROM orders WHERE client_id=?", (cid,)).fetchone()[0]
        rep["dup_ok"] = bool(r2.get("deduped")) and n == 1
        mgr.place(SYM, "SELL", "MARKET", qty, client_id=cid + "-close")
        time.sleep(2)

        # 3) vong mo/dong + reconcile moi vong (1 manager, 1 DB xuyen suot)
        cyc = 0
        while cyc < a.cycles and time.time() < deadline:
            tag = "soak-%d-%d" % (cyc, int(time.time() * 1000))
            mgr.place(SYM, "BUY", "MARKET", qty, client_id=tag + "-o")
            mgr.place_algo(SYM, "SELL", "STOP_MARKET", "0.00001", client_id=tag + "-sl")
            mgr.place(SYM, "SELL", "MARKET", qty, client_id=tag + "-c")
            time.sleep(3)  # doi tick mock expire SL + WS event ve
            rep["reconcile_diffs"] += rec.check()
            cyc += 1
            rep["cycles"] = cyc
            for p in ("", "-wal", "-shm"):
                fp = db_path + p
                if os.path.exists(fp):
                    rep.setdefault("wal_" + (p or "db"), []).append(os.path.getsize(fp))
            time.sleep(2)

        # 4) restart giua position: mo DB lai (mo phong restart container)
        keep = "soak-keep-%d" % int(time.time() * 1000)
        mgr.place(SYM, "BUY", "MARKET", qty, client_id=keep)
        for _ in range(10):  # doi WS event ve DB truoc khi check
            r = con.execute(
                "SELECT amt FROM positions WHERE symbol=?", (SYM,)).fetchone()
            if r and float(r[0]) != 0:
                break
            time.sleep(2)
        con2 = connect(db_path)
        mgr2 = OrderManager(con2, RestClient(BASE, "soak-key", SECRET), strategy="soak")
        row = con2.execute(
            "SELECT status FROM orders WHERE client_id=?", (keep,)).fetchone()
        rec2 = Reconciler(con2, RestClient(BASE, "soak-key", SECRET), None)
        rep["restart_ok"] = row is not None and rec2.check() == 0
        mgr.place(SYM, "SELL", "MARKET", qty, client_id=keep + "-close")
        time.sleep(2)

        # 5) ws drop + reconnect key cu
        for _ in range(a.drops):
            w = create_connection("ws://127.0.0.1:8081/ws/" + lk, timeout=8)
            _admin("/_admin/ws/drop")
            w.close()
            w2 = create_connection("ws://127.0.0.1:8081/ws/" + lk, timeout=8)
            w2.close()
            rest.put_keyalive(lk)
            rep["ws_drops"] += 1
            rep["reconnect_ok"] += 1

        # 6) quet orphan cuoi (poll toi flat, toi da 60s)
        ws_state["stop"] = True
        ok_flat = _wait_flat(rest, 60)
        oo = rest.get("/fapi/v1/openOrders")
        ao = rest.get("/fapi/v1/openAlgoOrders")
        pr = rest.get("/fapi/v2/positionRisk")
        open_pos = [p for p in (pr if isinstance(pr, list) else []) if float(p.get("positionAmt", 0)) != 0]
        rep["final"] = {"openOrders": len(oo), "openAlgo": len(ao.get("orders", [])),
                        "positions": len(open_pos), "wait_flat_ok": ok_flat}
        rep["pass"] = (rep["orphans"] == 0 and rep["final"]["openOrders"] == 0
                       and rep["final"]["positions"] == 0 and rep["dup_ok"] and rep["restart_ok"]
                       and rep["reconnect_ok"] == rep["ws_drops"] and rep["chaos_backoff_ok"])
    except Exception as e:
        rep["errors"].append("%s: %s" % (type(e).__name__, str(e)[:200]))
        rep["pass"] = False
    rep["t1"] = int(time.time() * 1000)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if not str(k).startswith("wal")},
                     ensure_ascii=False))
    return 0 if rep.get("pass") else 3


if __name__ == "__main__":
    raise SystemExit(main())
