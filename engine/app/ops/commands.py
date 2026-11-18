"""Kill switch 3 cap P1.3: pause / resume / flatten / stop qua bang `commands`.

Dashboard chi duoc ghi vao bang nay (Node read-only + allowlist), Python thuc thi.
Muc tieu: tu luc insert toi khi flat < 2s (do o integration).
"""

from __future__ import annotations

import time

from ..ops.log import log

ALLOWED = ("pause", "resume", "flatten", "stop")


def _now_ms() -> int:
    return int(time.time() * 1000)


def enqueue(con, action: str, payload: str = "", now_ms: int | None = None) -> int:
    """Ghi 1 command NEW. Khong validate action o day — handle_once se tu choi."""
    cur = con.execute(
        "INSERT INTO commands(action,payload,status,created_ms) VALUES(?,?,'NEW',?)",
        (action, payload, now_ms or _now_ms()),
    )
    return int(cur.lastrowid or 0)


def pending(con) -> list[tuple]:
    return con.execute(
        "SELECT id, action, payload FROM commands WHERE status='NEW' ORDER BY id"
    ).fetchall()


def _set_state(con, key: str, value: str, now: int) -> None:
    con.execute(
        "INSERT INTO runtime_state(key,value,updated_ms) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_ms=excluded.updated_ms",
        (key, value, now),
    )


def flatten_all(con, ex) -> list[str]:
    """Dong moi vi the dang mo. Tra ve danh sach symbol da dong."""
    syms = [
        str(r[0])
        for r in con.execute(
            "SELECT symbol FROM positions WHERE state='OPEN' AND CAST(amt AS REAL) != 0"
        ).fetchall()
    ]
    for sym in syms:
        ex.close(sym, "flatten")
    return syms


def handle_once(con, ex, now_ms: int | None = None) -> dict:
    """Xu ly tat ca command NEW. Tra ve {done, rejected}. Idempotent theo status."""
    done = rejected = 0
    for cid, action, _payload in pending(con):
        now = now_ms or _now_ms()
        act = str(action).strip().lower()
        if act not in ALLOWED:
            con.execute("UPDATE commands SET status='REJECTED', done_ms=? WHERE id=?", (now, cid))
            con.execute(
                "INSERT INTO incidents(kind,detail,ts_ms) VALUES('bad_command',?,?)",
                (str(action), now),
            )
            rejected += 1
            log("warn", "cmd.rejected", action=str(action))
            continue
        if act == "pause":
            _set_state(con, "paused", "1", now)
        elif act == "resume":
            _set_state(con, "paused", "0", now)
        elif act == "flatten":
            flatten_all(con, ex)
        elif act == "stop":
            flatten_all(con, ex)
            _set_state(con, "halted", "1", now)
        con.execute("UPDATE commands SET status='DONE', done_ms=? WHERE id=?", (now, cid))
        done += 1
        log("info", "cmd.done", action=act)
    return {"done": done, "rejected": rejected}


def run_loop(con, ex, stop_event, interval: float = 0.2) -> None:
    """Vong lap nen trong main.py. Dung stop_event.wait de khong busy-wait."""
    while not stop_event.wait(interval):
        try:
            handle_once(con, ex)
        except Exception as e:  # mot command loi khong duoc giet engine
            log("error", "cmd.loop_error", error=str(e)[:150])
