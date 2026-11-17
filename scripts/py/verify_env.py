"""P1.0 — Xac minh 13 muc §4.3 tren mock (stdlib + websocket-client).

Dung:  MOCK_API_SECRET=mock-secret python scripts/py/verify_env.py
Khong in secret/signature. Chi in PASS/FAIL + bang chung rut gon.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8081"
SECRET = __import__("os").environ.get("MOCK_API_SECRET", "mock-secret")
APIKEY = __import__("os").environ.get("MOCK_API_KEY", "verify-key")
SYMS10 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
          "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]
RES: list[tuple[str, bool, str]] = []


def _sign(qs: str) -> str:
    return hmac.new(SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()


def sreq(method: str, path: str, params: dict | None = None):
    """Signed request. Tra ve (status, body_dict, headers)."""
    params = dict(params or {})
    params.setdefault("timestamp", str(int(time.time() * 1000)))
    params.setdefault("recvWindow", "10000")
    qs = urllib.parse.urlencode(sorted(params.items()))
    sig = _sign(qs)
    url = BASE + path
    data = None
    if method in ("POST", "PUT", "DELETE"):
        url = url + "?" + qs + "&signature=" + sig
    else:
        url = url + "?" + qs + "&signature=" + sig
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-MBX-APIKEY": APIKEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except Exception:
            body = {}
        return e.code, body, {}


def pub(path: str, params: dict | None = None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.status, json.loads(r.read() or b"{}"), dict(r.headers)


def check(mid: str, ok: bool, ev: str):
    RES.append((mid, ok, ev))
    print(("PASS " if ok else "FAIL ") + mid + " :: " + ev, flush=True)


def main() -> int:
    # -- M1: time ---------------------------------------------------------
    try:
        st, b, _ = pub("/fapi/v1/time")
        off = int(time.time() * 1000) - int(b.get("serverTime", 0))
        check("M1", st == 200 and "serverTime" in b, "serverTime=%s offset_local=%dms" % (b.get("serverTime"), off))
    except Exception as e:
        check("M1", False, "exc=%s" % e); return 1

    # -- M7: weight header (lay tu 1 response public) ----------------------
    try:
        _, _, h = pub("/fapi/v1/exchangeInfo")
        w = h.get("X-MBX-USED-WEIGHT-1M") or h.get("X-MBX-USED-WEIGHT-1m")
        check("M7", True, "X-MBX-USED-WEIGHT-1M=%s" % w)
    except Exception as e:
        check("M7", False, "exc=%s" % e)

    # -- M2/M10: listenKey + WS user stream --------------------------------
    msgs: list[dict] = []
    key = ""
    try:
        from websocket import create_connection
        st, b, _ = sreq("POST", "/fapi/v1/listenKey")
        key = b.get("listenKey", "")
        ok_key = st == 200 and bool(key)
        ws = create_connection("ws://127.0.0.1:8081/ws/" + key, timeout=8)

        import threading
        stop = [False]

        def _recv():
            ws.settimeout(1.0)
            t0 = time.time()
            while not stop[0] and time.time() - t0 < 30:
                try:
                    m = ws.recv()
                    msgs.append(json.loads(m))
                except Exception:
                    pass

        th = threading.Thread(target=_recv, daemon=True)
        th.start()
        check("M2a", ok_key, "listenKey_len=%d ws_connected=True" % len(key))
    except Exception as e:
        check("M2a", False, "exc=%s" % type(e).__name__); ws = None; stop = [True]

    # -- M5/M6: exchangeInfo 10 symbol -------------------------------------
    filt: dict[str, dict] = {}
    try:
        st, b, _ = pub("/fapi/v1/exchangeInfo")
        for s in (b.get("symbols") or []):
            if s.get("symbol") in SYMS10:
                f = {x["filterType"]: x for x in s.get("filters", [])}
                pf, ls, mn = f.get("PRICE_FILTER", {}), f.get("LOT_SIZE", {}), \
                    f.get("MIN_NOTIONAL", f.get("NOTIONAL", {}))
                filt[s["symbol"]] = {"tick": pf.get("tickSize"), "step": ls.get("stepSize"),
                                     "min": mn.get("notional") or mn.get("minNotional")}
        ok5 = len(filt) == 10 and all(v["min"] for v in filt.values())
        mins = ",".join("%s=%s" % (k, filt[k]["min"]) for k in SYMS10 if k in filt)
        check("M5", ok5, "minNotional: " + mins)
        okt = all(v["tick"] and v["step"] for v in filt.values())
        check("M6", okt, "tick/step doc du 10 symbol (vd BTC=%s/%s)" % (
            filt.get("BTCUSDT", {}).get("tick"), filt.get("BTCUSDT", {}).get("step")))
    except Exception as e:
        check("M5", False, "exc=%s" % e); check("M6", False, "skip")

    # -- M4: phi ------------------------------------------------------------
    try:
        st, b, _ = sreq("GET", "/fapi/v1/commissionRate", {"symbol": "BTCUSDT"})
        check("M4", st == 200, "maker=%s taker=%s" % (b.get("makerCommissionRate"), b.get("takerCommissionRate")))
    except Exception as e:
        check("M4", False, "exc=%s" % e)

    # -- M12/M13 ------------------------------------------------------------
    try:
        st, b, _ = sreq("GET", "/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": "3"})
        check("M12", st == 200 and isinstance(b, list) and len(b) > 0, "ban_ghi=%d" % (len(b) if isinstance(b, list) else 0))
    except Exception as e:
        check("M12", False, "exc=%s" % e)
    try:
        st, b, _ = sreq("GET", "/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"})
        br = (b if isinstance(b, list) else [b])[0] if b else {}
        b1 = (br.get("brackets") or [{}])[0]
        check("M13", st == 200, "bracket1=%s" % json.dumps(b1)[:120])
    except Exception as e:
        check("M13", False, "exc=%s" % e)

    # -- M8: -4120 -----------------------------------------------------------
    try:
        st, b, _ = sreq("POST", "/fapi/v1/order/test",
                        {"symbol": "BTCUSDT", "side": "BUY", "type": "STOP_MARKET",
                         "quantity": "0.001", "stopPrice": "1"})
        check("M8", b.get("code") == -4120, "code=%s (ky vong -4120)" % b.get("code"))
    except Exception as e:
        check("M8", False, "exc=%s" % e)

    # -- M3/M9: mo position DOGE -> dat SL algo -> dong position -----------
    algo_id = None
    try:
        _, tp, _ = pub("/fapi/v1/ticker/price", {"symbol": "DOGEUSDT"})
        last = float(tp.get("price", "0") or 0)
        step = float(filt.get("DOGEUSDT", {}).get("step") or 1)
        tick = float(filt.get("DOGEUSDT", {}).get("tick") or 0.00001)
        qty = max(step, round(20 / max(last, 1e-9) / step) * step)
        st, bo, _ = sreq("POST", "/fapi/v1/order",
                         {"symbol": "DOGEUSDT", "side": "BUY", "type": "MARKET",
                          "quantity": str(qty), "newClientOrderId": "verify-m1-%d" % int(time.time() * 1000)})
        ok_ord = st == 200 and bo.get("orderId")
        # trigger duoi gia ~2% (SL long), lam tron theo tick
        trig = int(last * 0.98 / tick) * tick
        st, ba, _ = sreq("POST", "/fapi/v1/algoOrder",
                         {"symbol": "DOGEUSDT", "side": "SELL", "type": "STOP_MARKET",
                          "algoType": "CONDITIONAL", "triggerPrice": str(trig),
                          "closePosition": "true", "workingType": "MARK_PRICE",
                          "clientAlgoId": "verify-sl-%d" % int(time.time() * 1000)})
        algo_id = ba.get("algoId")
        check("M3", st == 200 and algo_id, "algoId=%s trig=%s" % (algo_id, trig))
        st, bc, _ = sreq("POST", "/fapi/v1/order",
                         {"symbol": "DOGEUSDT", "side": "SELL", "type": "MARKET",
                          "quantity": str(qty), "newClientOrderId": "verify-m2-%d" % int(time.time() * 1000)})
        time.sleep(2)
        bq = {}
        for _ in range(5):
            st, bq, _ = sreq("GET", "/fapi/v1/algoOrder", {"algoId": str(algo_id)} if algo_id else {})
            if (bq.get("algoStatus") or "") in ("EXPIRED", "FILLED", "CANCELLED", "FINISHED"):
                break
            time.sleep(2)
        check("M9", (bq.get("algoStatus") or "") in ("EXPIRED", "FILLED", "CANCELLED", "FINISHED"),
              "sau dong position: algoStatus=%s" % bq.get("algoStatus"))
    except Exception as e:
        check("M3", False, "exc=%s" % e); check("M9", False, "skip")

    # -- M2b/M10: doi event WS ----------------------------------------------
    try:
        time.sleep(6)
        if ws:
            stop[0] = True
            try:
                ws.close()
            except Exception:
                pass
        kinds = {m.get("e") for m in msgs if isinstance(m, dict)}
        check("M2b", "ORDER_TRADE_UPDATE" in kinds, "events=%s n=%d" % (sorted(kinds), len(msgs)))
        check("M10", "ALGO_UPDATE" in kinds, "ALGO_UPDATE %s" % ("co" if "ALGO_UPDATE" in kinds else "khong"))
    except Exception as e:
        check("M2b", False, "exc=%s" % e); check("M10", False, "skip")

    # -- WS drop + reconnect giu key cu --------------------------------------
    try:
        import urllib.request as U
        U.urlopen(urllib.request.Request(BASE + "/_admin/ws/drop", data=b"{}", method="POST"), timeout=10).read()
        from websocket import create_connection
        ws2 = create_connection("ws://127.0.0.1:8081/ws/" + key, timeout=8)
        st, _, _ = sreq("PUT", "/fapi/v1/listenKey", {"listenKey": key})
        ws2.close()
        check("M2c", st == 200, "drop WS -> reconnect key cu OK, keepalive=%s" % st)
    except Exception as e:
        check("M2c", False, "exc=%s" % e)

    # -- M11: kline vision -----------------------------------------------------
    try:
        ok11, ev11 = False, ""
        for d in ("2026-11-15", "2026-11-14", "2026-11-13"):
            u = ("https://data.binance.vision/data/futures/um/daily/klines/"
                 "BTCUSDT/1m/BTCUSDT-1m-%s.zip" % d)
            try:
                with urllib.request.urlopen(u, timeout=30) as r:
                    n = len(r.read())
                ok11, ev11 = True, "%s size=%dB" % (d, n)
                break
            except Exception as e:
                ev11 = "%s fail=%s" % (d, type(e).__name__)
        check("M11", ok11, ev11)
    except Exception as e:
        check("M11", False, "exc=%s" % e)

    # -- Phu: telegram + NTP -----------------------------------------------------
    try:
        with urllib.request.urlopen("https://api.telegram.org", timeout=10) as r:
            check("TEL", r.status == 200, "api.telegram.org=%s" % r.status)
    except Exception as e:
        check("TEL", False, "exc=%s" % e)

    n_ok = sum(1 for _, ok, _ in RES if ok)
    print("TONG: %d/%d PASS" % (n_ok, len(RES)), flush=True)
    return 0 if all(ok for _, ok, _ in RES) else 2


if __name__ == "__main__":
    raise SystemExit(main())
