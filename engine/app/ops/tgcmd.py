"""Poll lenh Telegram read-only cho service soak.

Pham vi co tinh gioi han: chi 1 lenh /check72h, chi tra loi dung chat ID da cau hinh.
Khong dat/huy lenh, khong kill switch, khong doc secret. Le lenh khac -> bo qua.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

ALLOWED = ("check72h",)
REPLY_MIN_INTERVAL_S = 8.0

STATE_VI = {
    "pending": "CHƯA BẮT ĐẦU",
    "running": "ĐANG THỰC HIỆN",
    "done": "HOÀN THÀNH",
    "error": "LỖI",
}


def parse_command(text: str | None) -> str | None:
    """Tra ve ten lenh neu hop le, nguoc lai None."""
    if not text or not text.strip().startswith("/"):
        return None
    cmd = text.strip().split()[0][1:].split("@")[0].lower()
    return cmd if cmd in ALLOWED else None


def format_status_vi(rep: dict) -> str:
    """Bang trang thai tieng Viet cho /check72h."""
    st = str(rep.get("state", "pending"))
    head = "Soak 72h: %s" % STATE_VI.get(st, st.upper())
    if st == "running":
        t0, dl = rep.get("t0", 0), rep.get("deadline", 0)
        now = int(time.time() * 1000)
        el_h = max(0.0, (now - t0) / 3600000.0)
        left_h = max(0.0, (dl - now) / 3600000.0)
        head += " (giờ %.1f, còn ~%.1fh)" % (el_h, left_h)
    if st == "done":
        head += " — %s" % ("ĐẠT" if rep.get("pass") else "CHƯA ĐẠT")
    if st == "error":
        errs = rep.get("errors", [])
        head += " — %s" % (errs[-1] if errs else "không rõ")
    fin = rep.get("final", {})
    lines = [
        head,
        "Vòng: %s/%s · Orphan: %s · Reconcile diff: %s"
        % (
            rep.get("cycles", 0),
            rep.get("planned_cycles", "?"),
            rep.get("orphans", 0),
            rep.get("reconcile_diffs", 0),
        ),
        "WS drop/reconnect: %s/%s · Trùng ID: %s · Chaos: %s · Restart: %s"
        % (
            rep.get("ws_drops", 0),
            rep.get("reconnect_ok", 0),
            _ok(rep.get("dup_ok")),
            _ok(rep.get("chaos_backoff_ok")),
            _ok(rep.get("restart_ok")),
        ),
    ]
    if fin:
        lines.append(
            "Cuối kỳ: openOrders=%s openAlgo=%s positions=%s"
            % (fin.get("openOrders"), fin.get("openAlgo"), fin.get("positions"))
        )
    errs = rep.get("errors", [])
    lines.append("Lỗi: %s" % (errs[-1] if errs else "không"))
    return "\n".join(lines)


def _ok(v) -> str:
    return "OK" if v else ("CHƯA" if v is None else "FAIL")


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_status_html(rep: dict) -> str:
    """Bang monospace cho Telegram (parse_mode=HTML). Telegram khong render <table>."""
    st = str(rep.get("state", "pending"))
    title = "Soak 72h: %s" % STATE_VI.get(st, st.upper())
    if st == "running":
        t0, dl = rep.get("t0", 0), rep.get("deadline", 0)
        now = int(time.time() * 1000)
        el_h = max(0.0, (now - t0) / 3600000.0)
        left_h = max(0.0, (dl - now) / 3600000.0)
        title += " — %.1fh / còn ~%.1fh" % (el_h, left_h)
    if st == "done":
        title += " — %s" % ("ĐẠT" if rep.get("pass") else "CHƯA ĐẠT")
    if st == "error":
        errs = rep.get("errors", [])
        title += " — %s" % (errs[-1] if errs else "không rõ")
    fin = rep.get("final", {})
    rows = [
        ("Vòng", "%s/%s" % (rep.get("cycles", 0), rep.get("planned_cycles", "?"))),
        ("Orphan", str(rep.get("orphans", 0))),
        ("Reconcile diff", str(rep.get("reconcile_diffs", 0))),
        ("WS drop/recon", "%s/%s" % (rep.get("ws_drops", 0), rep.get("reconnect_ok", 0))),
        ("Trùng ID", _ok(rep.get("dup_ok"))),
        ("Chaos backoff", _ok(rep.get("chaos_backoff_ok"))),
        ("Restart", _ok(rep.get("restart_ok"))),
    ]
    if fin:
        rows.append(
            (
                "Cuối kỳ",
                "orders=%s algo=%s pos=%s"
                % (fin.get("openOrders"), fin.get("openAlgo"), fin.get("positions")),
            )
        )
    errs = rep.get("errors", [])
    rows.append(("Lỗi", errs[-1] if errs else "không"))
    width = max(len(k) for k, _ in rows)
    body = "\n".join("%-*s : %s" % (width, k, v) for k, v in rows)
    return "<b>%s</b>\n<pre>%s</pre>" % (_esc(title), _esc(body))


def _send(token: str, chat_id: str, text: str, parse_mode: str = "") -> dict:
    data = {"chat_id": chat_id, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def _fetch(token: str, offset: int, timeout_s: int = 30) -> list:
    url = "https://api.telegram.org/bot%s/getUpdates?timeout=%d&offset=%d&allowed_updates=%s" % (
        token,
        timeout_s,
        offset,
        urllib.parse.quote('["message"]'),
    )
    with urllib.request.urlopen(url, timeout=timeout_s + 10) as r:
        body = json.loads(r.read() or b"{}")
    return body.get("result", []) if body.get("ok") else []


class CommandPoller:
    """Long-poll getUpdates trong thread. fetcher/sender inject duoc de test."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        status_fn,
        sender=_send,
        fetcher=_fetch,
        offset_path: str | None = None,
    ):
        self._token = token
        self._chat = str(chat_id)
        self._status_fn = status_fn
        self._sender = sender
        self._fetcher = fetcher
        self._offset_path = offset_path
        self._offset = self._load_offset()
        self._last_reply = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _load_offset(self) -> int:
        try:
            if self._offset_path:
                with open(self._offset_path, encoding="utf-8") as f:
                    return int(f.read().strip() or 0)
        except (OSError, ValueError):
            pass
        return 0

    def _save_offset(self) -> None:
        try:
            if self._offset_path:
                with open(self._offset_path, "w", encoding="utf-8") as f:
                    f.write(str(self._offset))
        except OSError:
            pass

    def start(self) -> None:
        from app.ops.log import log as _log

        _log("info", "tgcmd.start", chat_set=bool(self._chat))
        self._thread = threading.Thread(target=self._loop, name="tgcmd", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def handle_update(self, upd: dict) -> bool:
        """Xu ly 1 update. Tra ve True neu da tra loi."""
        msg = upd.get("message", {}) or {}
        chat = msg.get("chat", {}) or {}
        if str(chat.get("id", "")) != self._chat:
            return False
        if parse_command(msg.get("text", "")) != "check72h":
            return False
        now = time.time()
        if now - self._last_reply < REPLY_MIN_INTERVAL_S:
            return False
        try:
            html = format_status_html(self._status_fn())
            try:
                self._sender(self._token, self._chat, html, parse_mode="HTML")
            except TypeError:
                self._sender(self._token, self._chat, html)
            self._last_reply = now
            return True
        except Exception:
            return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                updates = self._fetcher(self._token, self._offset)
            except Exception:
                time.sleep(5.0)
                continue
            for u in updates:
                self._offset = max(self._offset, int(u.get("update_id", 0)) + 1)
                self.handle_update(u)
            self._save_offset()
