"""WS: reconnect, listenKey renew, stale, URL market. Stub server local."""

import threading
import time

from app.exchange import ws as W


def _stub_server(port, msgs, hold_s=0.2):
    from websockets.sync.server import serve

    def handler(sv):
        for m in msgs:
            try:
                sv.send(m)
            except Exception:
                return
        time.sleep(hold_s)

    srv = serve(handler, "127.0.0.1", port)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def test_recv_and_reconnect_counts():
    got = []
    srv = _stub_server(18761, ['{"e":"ping"}'], hold_s=0.3)
    c = W.WsConnection("t", lambda: "ws://127.0.0.1:18761", got.append, recv_timeout=2.0)
    c.start()
    time.sleep(4.0)
    c.stop()
    srv.shutdown()
    assert got, "khong nhan duoc msg nao"
    assert c.reconnects >= 1, "khong reconnect khi server dong"


def test_stale_flag():
    c = W.WsConnection("t", lambda: "ws://127.0.0.1:19999", lambda e: None)
    assert c.is_stale() is True  # chua co msg -> stale
    c.last_msg_ts = time.time()
    assert c.is_stale() is False


def test_listenkey_keeper_renews():
    calls = {"n": 0}

    class FakeRest:
        def post(self, path):
            calls["n"] += 1
            return {"listenKey": "k%d" % calls["n"]}

        def put_keyalive(self, key):
            if calls.get("fail"):
                raise RuntimeError("het han")
            return {}

    k = W.ListenKeyKeeper(FakeRest(), interval_s=0.2)
    assert k.ensure() == "k1"
    k.start()
    time.sleep(0.5)
    k.stop()
    assert calls["n"] == 1  # keepalive ok -> khong tao key moi


def test_listenkey_recreate_on_death():
    class FakeRest:
        def __init__(self):
            self.n = 0

        def post(self, path):
            self.n += 1
            return {"listenKey": "k%d" % self.n}

        def put_keyalive(self, key):
            raise RuntimeError("het han")

    fr = FakeRest()
    k = W.ListenKeyKeeper(fr, interval_s=0.2)
    k.ensure()
    k.start()
    time.sleep(0.5)
    k.stop()
    assert fr.n >= 2, "key chet phai tao moi"


def test_market_url_format():
    u = W.market_stream_url("wss://fstream.binance.com", ["btcusdt@kline_1m", "btcusdt@markPrice"])
    assert u == "wss://fstream.binance.com/stream?streams=btcusdt@kline_1m/btcusdt@markPrice"


def test_route_user_event():
    assert W.route_user_event({"e": "ORDER_TRADE_UPDATE"}) == "ORDER_TRADE_UPDATE"
    assert W.route_user_event({"e": "ALGO_UPDATE"}) == "ALGO_UPDATE"
    assert W.route_user_event({}) == ""
