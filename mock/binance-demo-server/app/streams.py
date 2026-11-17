"""User data stream: listenKey + WebSocket push event.

- listenKey song 60 phut, PUT gia han, DELETE dong.
- WS: /ws/<listenKey> va /private/ws/<listenKey> (duong dan that cua Binance).
"""
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from fastapi import WebSocket

from . import errors as E
from . import events
from .config import CFG


class _Client:
    __slots__ = ("ws", "queue", "listen_key")

    def __init__(self, ws: WebSocket, listen_key: str) -> None:
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.listen_key = listen_key


class StreamHub:
    def __init__(self) -> None:
        self._keys: dict[str, float] = {}
        self._clients: list[_Client] = []

    # ------------------------------------------------------------ listenKey

    def create(self) -> str:
        for k, exp in list(self._keys.items()):
            if exp > time.time():
                self._keys[k] = time.time() + CFG.listenkey_ttl_s
                return k
        key = secrets.token_urlsafe(48)[:60]
        self._keys[key] = time.time() + CFG.listenkey_ttl_s
        return key

    def keepalive(self, key: str) -> None:
        if key not in self._keys or self._keys[key] <= time.time():
            self._keys.pop(key, None)
            raise E.err(E.INVALID_LISTEN_KEY)
        self._keys[key] = time.time() + CFG.listenkey_ttl_s

    def close(self, key: str) -> None:
        self._keys.pop(key, None)
        for c in list(self._clients):
            if c.listen_key == key:
                self._detach(c)

    def is_valid(self, key: str) -> bool:
        exp = self._keys.get(key)
        return exp is not None and exp > time.time()

    def check_expired(self) -> None:
        now = time.time()
        for k, exp in list(self._keys.items()):
            if exp <= now:
                self._keys.pop(k, None)
                events.publish("listenKeyExpired", {
                    "e": "listenKeyExpired", "E": int(now * 1000), "listenKey": k})

    # ------------------------------------------------------------ clients

    async def attach(self, ws: WebSocket, key: str) -> None:
        from fastapi import WebSocketDisconnect

        await ws.accept()
        client = _Client(ws, key)
        self._clients.append(client)
        sender = asyncio.create_task(self._sender(client))
        try:
            # Chi cho client dong ket noi; khong xu ly message tu client.
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            sender.cancel()
            self._detach(client)

    async def _sender(self, client: _Client) -> None:
        try:
            while True:
                payload = await client.queue.get()
                await client.ws.send_json(payload)
        except (asyncio.CancelledError, RuntimeError):
            pass

    def _detach(self, client: _Client) -> None:
        if client in self._clients:
            self._clients.remove(client)

    def broadcast(self, kind: str, payload: dict[str, Any]) -> None:
        for c in list(self._clients):
            try:
                c.queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover
                self._detach(c)

    # ------------------------------------------------------------ debug

    def snapshot(self) -> dict:
        return {"keys": len(self._keys), "clients": len(self._clients)}


HUB = StreamHub()


def _on_event(kind: str, payload: dict) -> None:
    HUB.broadcast(kind, payload)


events.subscribe(_on_event)
