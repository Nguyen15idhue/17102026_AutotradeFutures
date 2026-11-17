"""Soak status/prune + /check72h poller. Hermetic (khong mang)."""

import os
import time

from app.ops.tgcmd import CommandPoller, format_status_vi, parse_command
from app.soak import blank_report, prune_old, read_status, write_status


def test_parse_command():
    assert parse_command("/check72h") == "check72h"
    assert parse_command("/check72h@botname") == "check72h"
    assert parse_command("/CHECK72H") == "check72h"
    assert parse_command("check72h") is None
    assert parse_command("/kill") is None
    assert parse_command("") is None
    assert parse_command(None) is None


def test_format_status_running():
    rep = blank_report()
    rep.update(
        {
            "state": "running",
            "cycles": 3,
            "planned_cycles": 25,
            "deadline": int(time.time() * 1000) + 3600000,
        }
    )
    txt = format_status_vi(rep)
    assert "ĐANG THỰC HIỆN" in txt and "3/25" in txt and "Orphan: 0" in txt


def test_format_status_done_error():
    rep = blank_report()
    rep.update({"state": "done", "pass": True})
    assert "ĐẠT" in format_status_vi(rep)
    rep.update({"state": "error", "errors": ["boom: x"]})
    assert "LỖI" in format_status_vi(rep) and "boom" in format_status_vi(rep)


def test_status_roundtrip(tmp_path):
    p = str(tmp_path / "soak-status.json")
    rep = blank_report()
    rep["state"] = "running"
    write_status(p, rep)
    back = read_status(p)
    assert back["state"] == "running"
    assert read_status(str(tmp_path / "nope.json"))["state"] == "pending"


def test_prune_old(tmp_path):
    old = tmp_path / "soak-report.json"
    new = tmp_path / "soak-status.json"
    keep = tmp_path / "bot.db"
    old.write_text("{}")
    new.write_text("{}")
    keep.write_text("{}")
    ancient = time.time() - 8 * 86400
    os.utime(old, (ancient, ancient))
    assert prune_old(str(tmp_path)) == 1
    assert not old.exists() and new.exists() and keep.exists()


def _poller(monkey=None, chat="-5456437520"):
    sent = []
    seen = {"n": 0}

    def fake_fetch(token, offset, timeout_s=30):
        seen["n"] += 1
        if seen["n"] == 1:
            return [
                {"update_id": 10, "message": {"chat": {"id": -5456437520}, "text": "/check72h"}}
            ]
        return []

    rep = blank_report()
    rep.update({"state": "running", "cycles": 1, "planned_cycles": 2})
    p = CommandPoller(
        "tok",
        chat,
        lambda: rep,
        sender=lambda t, c, x: sent.append(x) or {"ok": True},
        fetcher=fake_fetch,
    )
    return p, sent


def test_format_html_pending_shows_chua():
    from app.ops.tgcmd import format_status_html

    txt = format_status_html(blank_report())
    assert "<b>" in txt and "<pre>" in txt and "CHƯA" in txt


def test_poller_answers_once_then_ratelimit():
    p, sent = _poller()
    assert (
        p.handle_update(
            {"update_id": 10, "message": {"chat": {"id": -5456437520}, "text": "/check72h"}}
        )
        is True
    )
    assert len(sent) == 1 and "<pre>" in sent[0] and "ĐANG THỰC HIỆN" in sent[0]
    # ngay lap tuc goi lai -> rate limit, khong gui
    assert (
        p.handle_update(
            {"update_id": 11, "message": {"chat": {"id": -5456437520}, "text": "/check72h"}}
        )
        is False
    )
    assert len(sent) == 1


def test_poller_ignores_wrong_chat_and_cmd():
    p, sent = _poller()
    assert (
        p.handle_update({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/check72h"}})
        is False
    )
    assert (
        p.handle_update({"update_id": 2, "message": {"chat": {"id": -5456437520}, "text": "/kill"}})
        is False
    )
    assert (
        p.handle_update({"update_id": 3, "message": {"chat": {"id": -5456437520}, "text": "hello"}})
        is False
    )
    assert sent == []


def test_reconcile_alerts_only_on_rising_edge():
    from app.db.store import connect
    from app.exchange.reconcile import Reconciler

    class FakeRest:
        def __init__(self, amt="5"):
            self.amt = amt

        def get(self, path, params=None, signed=True):
            if path == "/fapi/v2/positionRisk":
                return [{"symbol": "DOGEUSDT", "positionAmt": self.amt}]
            return []

    class FakeAlert:
        def __init__(self):
            self.n = 0

        def push(self, key, text):
            return "queued"

        def flush(self):
            self.n += 1
            return 1

    con = connect(":memory:")
    al = FakeAlert()
    r = Reconciler(con, FakeRest("5"), al)
    assert r.check() == 1 and al.n == 1
    assert r.check() == 1 and al.n == 1, "da halt roi thi khong alert nua"
