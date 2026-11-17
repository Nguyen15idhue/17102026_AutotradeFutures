"""WS client: market + user stream, auto-reconnect, keepalive listenKey, stale detect.

Mock chi co user stream (/ws/<key>); market stream (kline/markPrice/bookTicker/aggTrade)
dung dinh dang Binance live, test bang stub o P1.1 (khong co `if mock:` — chi khac URL)."""

from __future__ import annotations

import json
import threading
import time

STALE_AFTER_S = 3.0
LISTENKEY_RENEW_S = 25 * 60  # renew truoc 30 phut


def market_stream_url(base_ws: str, streams: list[str]) -> str:
    """Dinh dang combined stream cua Binance: /stream?streams=a/b/c."""
    return base_ws.rstrip("/") + "/stream?streams=" + "/".join(streams)


class WsConnection:
    """Mot ket noi WS voi reconnect backoff. on_msg(event_dict)."""

    def __init__(self, name: str, url_fn, on_msg, recv_timeout: float = 30.0):
        self.name = name
        self._url_fn = url_fn  # goi moi lan reconnect (listenKey co the doi)
        self._on_msg = on_msg
        self._recv_timeout = recv_timeout
        self.last_msg_ts = 0.0
        self.reconnects = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def is_stale(self, after_s: float = STALE_AFTER_S) -> bool:
        return (time.time() - self.last_msg_ts) > after_s if self.last_msg_ts else True

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ws-" + self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        import websockets.sync.client as ws_sync

        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_sync.connect(self._url_fn(), max_size=2**20)
            except Exception:
                time.sleep(backoff)
                backoff = min(30.0, backoff * 2)
                continue
            try:
                ws.socket.settimeout(self._recv_timeout)
                backoff = 1.0
                while not self._stop.is_set():
                    try:
                        raw = ws.recv(timeout=self._recv_timeout)
                    except Exception:
                        break  # timeout hoac loi -> reconnect
                    self.last_msg_ts = time.time()
                    try:
                        self._on_msg(json.loads(raw))
                    except Exception:
                        pass
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
                if not self._stop.is_set():
                    self.reconnects += 1
                    time.sleep(backoff)
                    backoff = min(30.0, backoff * 2)


class ListenKeyKeeper:
    """Tao + giu listenKey qua REST. renew truoc 30 phut de khong mat event."""

    def __init__(self, rest, interval_s: float = LISTENKEY_RENEW_S):
        self._rest = rest
        self._interval = interval_s
        self.key = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def ensure(self) -> str:
        if not self.key:
            self.key = str(self._rest.post("/fapi/v1/listenKey").get("listenKey", ""))
        return self.key

    def start(self) -> None:
        self.ensure()
        self._thread = threading.Thread(target=self._keep, name="listenkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _keep(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._rest.put_keyalive(self.key)
            except Exception:
                try:  # key chet -> tao moi
                    self.key = str(self._rest.post("/fapi/v1/listenKey").get("listenKey", ""))
                except Exception:
                    pass


def route_user_event(ev: dict) -> str:
    """Phan loai event user stream: ORDER_TRADE_UPDATE / ALGO_UPDATE / ACCOUNT_UPDATE."""
    return str(ev.get("e", ""))
