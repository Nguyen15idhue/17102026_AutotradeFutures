"""Canh bao Telegram outbound-only: hang doi + dedup + retry. Khong log token."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

DEDUP_WINDOW_S = 60.0


def _post(token: str, chat_id: str, text: str, topic_id: str = "") -> dict:
    data = {"chat_id": chat_id, "text": text}
    if topic_id:
        data["message_thread_id"] = topic_id
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


class Alerter:
    """sender injectable de test: sender(token, chat_id, text) -> dict."""

    def __init__(
        self, token: str, chat_id: str, topic_id: str = "", sender=_post, queue_max: int = 200
    ):
        self._token = token
        self._chat = chat_id
        self._topic = topic_id
        self._sender = sender
        self._queue: list[tuple[str, str]] = []
        self._qmax = queue_max
        self._last_sent: dict[str, float] = {}

    def enabled(self) -> bool:
        return bool(self._token and self._chat)

    def push(self, key: str, text: str) -> str:
        """Tra ve queued/deduped/disabled."""
        if not self.enabled():
            return "disabled"
        now = time.time()
        if now - self._last_sent.get(key, 0.0) < DEDUP_WINDOW_S:
            return "deduped"
        if len(self._queue) >= self._qmax:
            self._queue.pop(0)
        self._queue.append((key, text))
        return "queued"

    def flush(self) -> int:
        """Gui het hang doi, retry 3 lan moi tin. Tra ve so tin gui duoc."""
        sent = 0
        while self._queue:
            key, text = self._queue.pop(0)
            ok = False
            for _ in range(3):
                try:
                    if self._sender is _post:
                        res = _post(self._token, self._chat, text, self._topic)
                    else:
                        res = self._sender(self._token, self._chat, text)
                    ok = bool(res.get("ok", True))
                    break
                except Exception:
                    time.sleep(1.0)
            if ok:
                self._last_sent[key] = time.time()
                sent += 1
        return sent

    def pending(self) -> int:
        return len(self._queue)
