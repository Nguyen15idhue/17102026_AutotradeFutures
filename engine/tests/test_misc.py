"""Alert: queue + dedup + retry. Clock: offset."""

import time

from app.exchange import clock as C
from app.ops.alert import Alerter


def test_dedup_and_flush():
    sent = []

    def fake(token, chat, text):
        sent.append(text)
        return {"ok": True}

    a = Alerter("tok", "123", sender=fake)
    assert a.push("k1", "msg") == "queued"
    assert a.push("k1", "msg") == "queued"  # 2 tin khac key? khong — cung key nhung chua flush
    assert a.pending() == 2
    assert a.flush() == 2 and sent == ["msg", "msg"]
    # sau flush, cung key trong 60s -> deduped
    assert a.push("k1", "msg") == "deduped"


def test_retry_then_ok():
    tries = []

    def flaky(token, chat, text):
        tries.append(1)
        if len(tries) < 3:
            raise RuntimeError("net")
        return {"ok": True}

    a = Alerter("tok", "123", sender=flaky)
    a.push("k", "hi")
    assert a.flush() == 1 and len(tries) == 3


def test_disabled_without_token():
    a = Alerter("", "", sender=lambda *x: {"ok": True})
    assert a.push("k", "hi") == "disabled" and a.flush() == 0


def test_clock_offset():
    off = C.measure_offset(lambda: int(time.time() * 1000) + 500)
    assert 300 < off < 900  # ~500ms tru distance RTT/2
